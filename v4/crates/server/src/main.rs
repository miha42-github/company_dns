mod envelope;

use axum::{
    extract::{Path, Query, State},
    response::IntoResponse,
    routing::get,
    Router,
};
use company_dns_edgar::{EdgarCatalog, EdgarClient};
use company_dns_sic::{model_info, Embedders, SicCatalog};
use company_dns_wikipedia::WikipediaClient;
use envelope::{not_found, ok, server_error};
use serde::Deserialize;
use serde_json::json;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::Mutex;
use tower_http::cors::CorsLayer;

struct AppState {
    sic: SicCatalog,
    edgar_catalog: Option<EdgarCatalog>,
    edgar_client: EdgarClient,
    embedders: Mutex<Embedders>,
    wikipedia: WikipediaClient,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Defaults match the SIC/EDGAR staging convention decided in
    // docs/plans/v4-server-prototype.md sec4: repo-root ./tmp, not
    // under v4/.
    let sic_path = std::env::var("SIC_DATA_PATH")
        .unwrap_or_else(|_| "../../tmp/us_flat_embedded.feather".to_string());
    let edgar_catalog_path = std::env::var("EDGAR_CATALOG_PATH")
        .unwrap_or_else(|_| "../../tmp/edgar_10x_catalog.feather".to_string());

    println!("Loading US SIC data from {sic_path}...");
    let sic = SicCatalog::open(&sic_path).await?;

    let edgar_catalog = match EdgarCatalog::open(&PathBuf::from(&edgar_catalog_path)).await {
        Ok(catalog) => {
            println!("Loaded EDGAR catalog from {edgar_catalog_path}");
            Some(catalog)
        }
        Err(e) => {
            eprintln!(
                "WARNING: could not load EDGAR catalog from {edgar_catalog_path} ({e}) - \
                 ciks/detail/summary endpoints will return 404 until \
                 `cargo run --bin ingest-edgar -- <year> <quarter>` has been run. \
                 firmographics-by-CIK (the live-fallback path) is unaffected."
            );
            None
        }
    };

    let edgar_client = EdgarClient::new(company_dns_edgar::USER_AGENT)?;
    let wikipedia = WikipediaClient::new();

    let models_to_load: Vec<&'static str> = match std::env::var("SIC_MODELS").ok().as_deref() {
        Some("all_mpnet_base_v2") => vec!["all_mpnet_base_v2"],
        Some("both") => vec!["all_minilm_l6_v2", "all_mpnet_base_v2"],
        _ => vec!["all_minilm_l6_v2"], // go-duckdb-rewrite.md sec7.8's decision
    };
    println!("Loading embedding models: {models_to_load:?}...");
    let embedders = Embedders::load(&models_to_load)?;

    let state = Arc::new(AppState {
        sic,
        edgar_catalog,
        edgar_client,
        embedders: Mutex::new(embedders),
        wikipedia,
    });

    let app = Router::new()
        .route("/health", get(health))
        // US SIC, V3 parity (docs/plans/v4-server-prototype.md sec5.2)
        .route("/V4.0/na/sic/description/:sic_desc", get(sic_description))
        .route("/V4.0/na/sic/code/:sic_code", get(sic_code))
        .route("/V4.0/na/sic/division/:division_code", get(sic_division))
        .route("/V4.0/na/sic/industry/:industry_code", get(sic_industry))
        .route("/V4.0/na/sic/major/:major_code", get(sic_major))
        // US SIC similarity, V4-only (sec5.1)
        .route("/V4.0/na/sic/similarity/:query", get(sic_similarity))
        // EDGAR, V3 parity (sec5.3)
        .route(
            "/V4.0/na/companies/edgar/ciks/:company_name",
            get(edgar_ciks),
        )
        .route(
            "/V4.0/na/companies/edgar/detail/:company_name",
            get(edgar_detail),
        )
        .route(
            "/V4.0/na/companies/edgar/summary/:company_name",
            get(edgar_summary),
        )
        .route(
            "/V4.0/na/company/edgar/firmographics/:cik_no",
            get(edgar_firmographics),
        )
        // Staged, not built (sec8.1/8.2)
        .route(
            "/V4.0/global/company/wikipedia/firmographics/:company_name",
            get(wikipedia_firmographics),
        )
        .route(
            "/V4.0/global/company/merged/firmographics/:company_name",
            get(merged_firmographics),
        )
        .layer(CorsLayer::permissive())
        .with_state(state);

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(4000);
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", port)).await?;
    println!("company-dns V4 prototype listening on http://127.0.0.1:{port}");
    axum::serve(listener, app).await?;

    Ok(())
}

async fn health() -> &'static str {
    "ok"
}

// -------------------------------------------------------------- //
// US SIC, V3 parity

async fn sic_description(
    State(state): State<Arc<AppState>>,
    Path(sic_desc): Path<String>,
) -> impl IntoResponse {
    match state.sic.find_by_description(&sic_desc).await {
        Ok(matches) if !matches.is_empty() => ok(
            "SicCatalog->find_by_description",
            format!("{} SIC matches for [{sic_desc}]", matches.len()),
            json!(matches),
        )
        .into_response(),
        Ok(_) => not_found(
            "SicCatalog->find_by_description",
            format!("No SIC found for description [{sic_desc}]"),
        )
        .into_response(),
        Err(e) => server_error("SicCatalog->find_by_description", e.to_string()).into_response(),
    }
}

async fn sic_code(
    State(state): State<Arc<AppState>>,
    Path(sic_code): Path<String>,
) -> impl IntoResponse {
    match state.sic.find_by_code(&sic_code).await {
        Ok(matches) if !matches.is_empty() => ok(
            "SicCatalog->find_by_code",
            format!("{} SIC matches for [{sic_code}]", matches.len()),
            json!(matches),
        )
        .into_response(),
        Ok(_) => not_found(
            "SicCatalog->find_by_code",
            format!("No SIC found for code [{sic_code}]"),
        )
        .into_response(),
        Err(e) => server_error("SicCatalog->find_by_code", e.to_string()).into_response(),
    }
}

async fn sic_division(
    State(state): State<Arc<AppState>>,
    Path(division_code): Path<String>,
) -> impl IntoResponse {
    match state.sic.find_division(&division_code).await {
        Ok(matches) if !matches.is_empty() => ok(
            "SicCatalog->find_division",
            format!("{} division matches for [{division_code}]", matches.len()),
            json!(matches),
        )
        .into_response(),
        Ok(_) => not_found(
            "SicCatalog->find_division",
            format!("No division found for [{division_code}]"),
        )
        .into_response(),
        Err(e) => server_error("SicCatalog->find_division", e.to_string()).into_response(),
    }
}

async fn sic_industry(
    State(state): State<Arc<AppState>>,
    Path(industry_code): Path<String>,
) -> impl IntoResponse {
    match state.sic.find_industry_group(&industry_code).await {
        Ok(matches) if !matches.is_empty() => ok(
            "SicCatalog->find_industry_group",
            format!(
                "{} industry-group matches for [{industry_code}]",
                matches.len()
            ),
            json!(matches),
        )
        .into_response(),
        Ok(_) => not_found(
            "SicCatalog->find_industry_group",
            format!("No industry group found for [{industry_code}]"),
        )
        .into_response(),
        Err(e) => server_error("SicCatalog->find_industry_group", e.to_string()).into_response(),
    }
}

async fn sic_major(
    State(state): State<Arc<AppState>>,
    Path(major_code): Path<String>,
) -> impl IntoResponse {
    match state.sic.find_major_group(&major_code).await {
        Ok(matches) if !matches.is_empty() => ok(
            "SicCatalog->find_major_group",
            format!("{} major-group matches for [{major_code}]", matches.len()),
            json!(matches),
        )
        .into_response(),
        Ok(_) => not_found(
            "SicCatalog->find_major_group",
            format!("No major group found for [{major_code}]"),
        )
        .into_response(),
        Err(e) => server_error("SicCatalog->find_major_group", e.to_string()).into_response(),
    }
}

// -------------------------------------------------------------- //
// US SIC similarity, V4-only

#[derive(Deserialize)]
struct SimilarityParams {
    #[serde(default = "default_k")]
    k: usize,
    #[serde(default = "default_model")]
    model: String,
}

fn default_k() -> usize {
    10
}

fn default_model() -> String {
    "all_minilm_l6_v2".to_string()
}

async fn sic_similarity(
    State(state): State<Arc<AppState>>,
    Path(query): Path<String>,
    Query(params): Query<SimilarityParams>,
) -> impl IntoResponse {
    if model_info(&params.model).is_none() {
        return server_error(
            "SicCatalog->search_similar",
            format!("unknown model: {}", params.model),
        )
        .into_response();
    }
    let k = params.k.clamp(1, 50);

    let vector = {
        let mut embedders = state.embedders.lock().await;
        match embedders.embed_query(&params.model, &query) {
            Ok(v) => v,
            Err(e) => {
                return server_error("SicCatalog->search_similar", e.to_string()).into_response()
            }
        }
    };

    match state.sic.search_similar(&params.model, &vector, k).await {
        Ok(hits) => ok(
            "SicCatalog->search_similar",
            format!("{} similar SIC entries for [{query}]", hits.len()),
            json!(hits),
        )
        .into_response(),
        Err(e) => server_error("SicCatalog->search_similar", e.to_string()).into_response(),
    }
}

// -------------------------------------------------------------- //
// EDGAR, V3 parity

async fn edgar_ciks(
    State(state): State<Arc<AppState>>,
    Path(company_name): Path<String>,
) -> impl IntoResponse {
    let Some(catalog) = &state.edgar_catalog else {
        return server_error(
            "EdgarCatalog->find_by_name",
            "EDGAR catalog not loaded - run `cargo run --bin ingest-edgar` first",
        )
        .into_response();
    };
    match catalog.find_by_name(&company_name).await {
        Ok(matches) if !matches.is_empty() => {
            let ciks: std::collections::BTreeMap<String, u64> = matches
                .iter()
                .map(|m| (m.company_name.clone(), m.cik))
                .collect();
            ok(
                "EdgarCatalog->find_by_name",
                format!("{} CIK matches for [{company_name}]", ciks.len()),
                json!(ciks),
            )
            .into_response()
        }
        Ok(_) => not_found(
            "EdgarCatalog->find_by_name",
            format!("No CIK found for [{company_name}]"),
        )
        .into_response(),
        Err(e) => server_error("EdgarCatalog->find_by_name", e.to_string()).into_response(),
    }
}

async fn edgar_detail(
    State(state): State<Arc<AppState>>,
    Path(company_name): Path<String>,
) -> impl IntoResponse {
    edgar_detail_or_summary(state, company_name).await
}

async fn edgar_summary(
    State(state): State<Arc<AppState>>,
    Path(company_name): Path<String>,
) -> impl IntoResponse {
    edgar_detail_or_summary(state, company_name).await
}

/// V3's `detail` and `summary` endpoints both call
/// `EdgarQueries.get_all_details`, differing only in whether live
/// EDGAR firmographics get merged in per match (`firmographics=False`
/// for summary). V4's catalog-backed equivalent returns the same
/// catalog rows for both for now - the firmographics-per-match
/// enrichment `detail` adds in V3 is deferred until real usage shows
/// it's needed here too, rather than N live fetches per name search by
/// default.
async fn edgar_detail_or_summary(
    state: Arc<AppState>,
    company_name: String,
) -> axum::response::Response {
    let Some(catalog) = &state.edgar_catalog else {
        return server_error(
            "EdgarCatalog->find_by_name",
            "EDGAR catalog not loaded - run `cargo run --bin ingest-edgar` first",
        )
        .into_response();
    };
    match catalog.find_by_name(&company_name).await {
        Ok(matches) if !matches.is_empty() => ok(
            "EdgarCatalog->find_by_name",
            format!("{} filings found for [{company_name}]", matches.len()),
            json!(matches),
        )
        .into_response(),
        Ok(_) => not_found(
            "EdgarCatalog->find_by_name",
            format!("No company found for [{company_name}]"),
        )
        .into_response(),
        Err(e) => server_error("EdgarCatalog->find_by_name", e.to_string()).into_response(),
    }
}

async fn edgar_firmographics(
    State(state): State<Arc<AppState>>,
    Path(cik_no): Path<String>,
) -> impl IntoResponse {
    let cik: u64 = match cik_no.trim_start_matches('0').parse() {
        Ok(c) => c,
        Err(_) => {
            return server_error(
                "EdgarClient->get_firmographics",
                format!("invalid CIK: [{cik_no}]"),
            )
            .into_response()
        }
    };
    match state.edgar_client.get_firmographics(cik).await {
        Ok(data) => ok(
            "EdgarClient->get_firmographics",
            format!("Firmographics for CIK [{cik_no}]"),
            (*data).clone(),
        )
        .into_response(),
        Err(e) => not_found(
            "EdgarClient->get_firmographics",
            format!("No firmographics for CIK [{cik_no}]: {e}"),
        )
        .into_response(),
    }
}

// -------------------------------------------------------------- //
// Staged: Wikipedia + merged firmographics (sec8.1/8.2)

async fn wikipedia_firmographics(
    Path(company_name): Path<String>,
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    match state.wikipedia.get_firmographics(&company_name).await {
        Ok(data) => ok("WikipediaClient->get_firmographics", "ok", (*data).clone()).into_response(),
        Err(e) => not_found("WikipediaClient->get_firmographics", e.to_string()).into_response(),
    }
}

async fn merged_firmographics(
    Path(company_name): Path<String>,
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    let edgar_data = if let Some(catalog) = &state.edgar_catalog {
        match catalog.find_by_name(&company_name).await {
            Ok(matches) if !matches.is_empty() => Some(json!(matches)),
            _ => None,
        }
    } else {
        None
    };

    let wiki_err = state
        .wikipedia
        .get_firmographics(&company_name)
        .await
        .err()
        .map(|e| e.to_string());

    let merged = company_dns_firmographics::merge(&company_name, edgar_data, wiki_err);
    ok(
        "merge",
        format!("Merged firmographics for [{company_name}]"),
        merged,
    )
    .into_response()
}
