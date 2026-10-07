mod access;
mod docs;
mod envelope;
mod logging;
mod rate_limit;
mod sql_endpoint;
mod trusted_origin;
mod user_agent;

use axum::{
    extract::{Path, Query, State},
    response::IntoResponse,
};
use company_dns_edgar::{EdgarCatalog, EdgarClient};
use company_dns_sic::{company_match, model_info, Embedders, SicCatalog};
use company_dns_wikipedia::{WikipediaClient, WikipediaError};
use envelope::{bad_request, not_found, ok, server_error, ApiEnvelope};
use rate_limit::{tiered_rate_limit, TieredLimiterState};
use serde::Deserialize;
use serde_json::json;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tower::ServiceBuilder;
use tower_http::{
    cors::CorsLayer, limit::RequestBodyLimitLayer, services::ServeDir,
    set_header::SetResponseHeaderLayer, timeout::TimeoutLayer, trace::TraceLayer,
};
use utoipa::OpenApi;
use utoipa_axum::{router::OpenApiRouter, routes};
use utoipa_redoc::{Redoc, Servable};
use utoipa_swagger_ui::{Config, SwaggerUi};

struct AppState {
    sic: SicCatalog,
    edgar_catalog: Option<EdgarCatalog>,
    edgar_client: EdgarClient,
    embedders: Mutex<Embedders>,
    wikipedia: WikipediaClient,
    /// The experimental SQL endpoint (`sql_endpoint.rs`); `None` unless
    /// `COMPANY_DNS_SQL_ENABLED` is set.
    sql: Option<sql_endpoint::SqlState>,
}

/// `docs/plans/v4-openapi-docs.md` §3.4/§8: the OpenAPI document V4
/// publishes at `/openapi.json` (Swagger UI at `/docs`, ReDoc at
/// `/redoc` - matching V3's FastAPI `docs_url`/`redoc_url`/
/// `openapi_url` exactly, `company_dns.py:103-105`). Deliberately no
/// `paths(...)` here - every path comes from the `.routes(routes!(...))`
/// calls in `main()` via `OpenApiRouter::with_openapi`, which seeds
/// *this* doc's `info`/`components` and then has each `routes!(...)`
/// call append its own handlers' paths. Listing paths both here and in
/// `routes!(...)` double-registers them with Axum (`Router` panics on
/// the resulting "Overlapping method route" at startup - hit this
/// exact panic during implementation, fixed by removing the redundant
/// list here) - this is the one thing `utoipa-axum`'s "can't drift"
/// guarantee (§2) depends on: paths live in exactly one place.
#[derive(OpenApi)]
#[openapi(
    components(schemas(ApiEnvelope)),
    modifiers(&SecurityAddon),
    info(
        title = "company_dns API (V4)",
        version = "4.0.0",
        description = "Company firmographics and SIC code lookup service"
    )
)]
struct ApiDoc;

/// Declares the HTTP Basic security scheme the experimental SQL operation refers to.
struct SecurityAddon;

impl utoipa::Modify for SecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        use utoipa::openapi::security::{Http, HttpAuthScheme, SecurityScheme};
        openapi
            .components
            .get_or_insert_with(Default::default)
            .add_security_scheme("basic_auth", SecurityScheme::Http(Http::new(HttpAuthScheme::Basic)));
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // docs/plans/v4-dynamic-log-level.md: real structured logging,
    // first thing in main() so nothing below logs before a subscriber
    // exists (sec1's finding: TraceLayer's own events were previously
    // generated into a void with no subscriber to consume them).
    let log_reload_handle = logging::init();
    logging::spawn_config_watch(log_reload_handle, Duration::from_secs(5));

    // Data files: one directory (COMPANY_DNS_DATA_DIR - in the container image
    // the directory the files are copied into, in development the repo's
    // top-level tmp/), each file under its standard name, each overridable
    // by its own variable. See crates/edgar/src/data_dir.rs and
    // docs/plans/v4-deployment.md section 3.2. Independent of the working
    // directory the server was started from.
    tracing::info!(
        "Data directory: {} ({} unset: the repo-root tmp/ this build came from)",
        company_dns_edgar::data_dir::data_dir().display(),
        company_dns_edgar::data_dir::DATA_DIR_ENV
    );
    let sic_path = company_dns_edgar::data_dir::resolve("SIC_DATA_PATH", "us_flat_embedded.feather")
        .to_string_lossy()
        .into_owned();
    let edgar_catalog_path = company_dns_edgar::data_dir::resolve(
        "EDGAR_CATALOG_PATH",
        company_dns_edgar::data_dir::EDGAR_CATALOG_FILE,
    )
    .to_string_lossy()
    .into_owned();
    tracing::info!("Loading US SIC data from {sic_path}...");
    let mut sic = SicCatalog::open(&sic_path).await?;

    // docs/plans/sic-global-search.md: additional classification
    // systems register into the same catalog as they land, staged by
    // data availability (v4-initial-release-roadmap.md sec3a) - Japan
    // first, then EU NACE, then ISIC (Rev. 4). Each is optional, same "warn and continue"
    // pattern as the EDGAR catalog below: a missing file drops that
    // system from the global-search endpoints, not the whole server.
    // (env var, default file name in the data directory, table name, source_type label - the label
    // is what the UI's per-source pills/filters key on.)
    let extra_systems = [
        (
            "JAPAN_SIC_DATA_PATH",
            "japan_rev13_flat_embedded.feather",
            "sic_data_japan",
            "Japan SIC",
        ),
        (
            "EU_NACE_DATA_PATH",
            "nace_rev2_flat_embedded.feather",
            "sic_data_nace",
            "EU NACE",
        ),
        (
            "ISIC_DATA_PATH",
            "isic_rev4_flat_embedded.feather",
            "sic_data_isic",
            "ISIC",
        ),
    ];
    for (env_var, default_file, table, label) in extra_systems {
        let path = company_dns_edgar::data_dir::resolve(env_var, default_file)
            .to_string_lossy()
            .into_owned();
        match sic.register_system(&path, table, label).await {
            Ok(()) => tracing::info!("Loaded {label} data from {path}"),
            Err(e) => tracing::warn!(
                "could not load {label} data from {path} ({e}) - \
                 the global-search endpoints will skip {label} until this is available."
            ),
        }
    }

    let edgar_catalog = match EdgarCatalog::open(&PathBuf::from(&edgar_catalog_path)).await {
        Ok(catalog) => {
            tracing::info!("Loaded EDGAR catalog from {edgar_catalog_path}");
            Some(catalog)
        }
        Err(e) => {
            tracing::warn!(
                "could not load EDGAR catalog from {edgar_catalog_path} ({e}) - \
                 ciks/detail/summary endpoints will return 404 until \
                 `cargo run --release --bin ingest-edgar` (last two years of quarters) has been run. \
                 firmographics-by-CIK (the live-fallback path) is unaffected."
            );
            None
        }
    };

    let edgar_client = EdgarClient::new(company_dns_edgar::USER_AGENT)?;
    let wikipedia = WikipediaClient::new(company_dns_wikipedia::USER_AGENT)?;

    let models_to_load: Vec<&'static str> = match std::env::var("SIC_MODELS").ok().as_deref() {
        Some("all_mpnet_base_v2") => vec!["all_mpnet_base_v2"],
        Some("both") => vec!["all_minilm_l6_v2", "all_mpnet_base_v2"],
        _ => vec!["all_minilm_l6_v2"], // go-duckdb-rewrite.md sec7.8's decision
    };
    tracing::info!("Loading embedding models: {models_to_load:?}...");
    let embedders = Embedders::load(&models_to_load)?;

    // docs/plans/v4-sql-endpoint.md section 5a: profiles (HTTP Basic Auth). Two files, read
    // once at startup: credentials (passwd-style, the only secret) and optional rules (JSON,
    // defaults plus per-profile overrides). Both optional; with no credentials file every
    // caller is anonymous and tiered by User-Agent. A set but invalid file stops startup: it
    // never comes up half-configured.
    let non_empty = |name: &str| std::env::var(name).ok().filter(|p| !p.trim().is_empty());
    let access: Option<Arc<access::Access>> = match (non_empty("COMPANY_DNS_CREDENTIALS_FILE"), non_empty("COMPANY_DNS_RULES_FILE")) {
        (None, None) => None,
        (None, Some(_)) => anyhow::bail!("COMPANY_DNS_RULES_FILE is set but COMPANY_DNS_CREDENTIALS_FILE is not: rules need credentials to apply to"),
        (Some(creds), rules) => {
            let profiles = access::Profiles::load(
                std::path::Path::new(&creds),
                rules.as_deref().map(std::path::Path::new),
            )?;
            tracing::info!(
                "Profiles: {} loaded from {creds}{}: {:?}",
                profiles.len(),
                rules.as_ref().map(|r| format!(" with rules from {r}")).unwrap_or_else(|| " (no rules file: no grants)".to_string()),
                profiles.ids()
            );
            Some(Arc::new(access::Access::new(profiles)))
        }
    };

    // Off unless COMPANY_DNS_SQL_ENABLED. With it on, a bad setting or no credentials file
    // stops startup: the endpoint never comes up open.
    let sql = match sql_endpoint::SqlConfig::from_lookup(&|k| std::env::var(k).ok())? {
        None => None,
        Some(config) => {
            let access = access.clone().ok_or_else(|| anyhow::anyhow!(
                "COMPANY_DNS_SQL_ENABLED is set but COMPANY_DNS_CREDENTIALS_FILE is not: the SQL endpoint will not start without credentials"
            ))?;
            let sql = sql_endpoint::SqlState::build(config, access, &sic, edgar_catalog.as_ref()).await?;
            tracing::warn!("{}", sql.describe());
            Some(sql)
        }
    };

    let state = Arc::new(AppState {
        sic,
        edgar_catalog,
        edgar_client,
        embedders: Mutex::new(embedders),
        wikipedia,
        sql,
    });

    // docs/plans/v4-security-hardening.md §3.1a/§5 step 2: `/health`
    // (kubelet's liveness/readiness probe target,
    // k8s/prod/deployment.yaml) and the introspection routes
    // (/docs, /redoc, /openapi.json, merged in below after
    // split_for_parts) all stay OUTSIDE the rate-limit gate - a
    // rate-limited health check would make Kubernetes think a healthy
    // pod is failing and kill it. `data_router` carries every other
    // route and gets `.layer(...)`'d with the rate limiter BEFORE
    // merging `health_router` in unlayered, so the layer only ever
    // wraps the routes that were part of `data_router` at the time
    // `.layer(...)` was called (`OpenApiRouter::layer` is a pass-
    // through to `axum::Router::layer`, same "layer wraps what's
    // already there, not what's merged in after" semantics).
    let tiered_limiter_state = TieredLimiterState::new(access.clone());
    tiered_limiter_state.spawn_periodic_sweep(Duration::from_secs(5 * 60));

    let health_router = OpenApiRouter::new().routes(routes!(health));

    // The experimental SQL route: only when enabled. It goes through the same rate limiter
    // as the lookups (User-Agent tiers, a profile's rate_limit grant, the same buckets), but
    // WITHOUT the trusted-Origin bypass, since that header is client-set. On top of that,
    // the handler authenticates every request itself and applies the profile's own SQL
    // limits (sql_endpoint.rs).
    let sql_router = if state.sql.is_some() {
        OpenApiRouter::new().routes(routes!(sql_query)).layer(axum::middleware::from_fn_with_state(
            tiered_limiter_state.without_origin_trust(),
            tiered_rate_limit,
        ))
    } else {
        OpenApiRouter::new()
    };

    // Each `routes!(...)` call is ONE path - the macro bundles multiple
    // handlers together only when they share a path and differ by HTTP
    // method (e.g. GET+POST on the same route), not when they're
    // different paths. Learned this the hard way: bundling a V4.0
    // handler with its V3.0 alias in one `routes!(a, b)` call panics at
    // startup ("Overlapping method route... both handle GET"), since
    // the macro tried to mount both as GET on the same route entry.
    // Every handler - including every `_v3` alias - gets its own call.
    let data_router = OpenApiRouter::new()
        // US SIC, V3 parity (docs/plans/v4-server-prototype.md sec5.2) +
        // V3.0 backward-compat aliases (v4-openapi-docs.md sec8)
        .routes(routes!(sic_description))
        .routes(routes!(sic_description_v3))
        .routes(routes!(sic_code))
        .routes(routes!(sic_code_v3))
        .routes(routes!(sic_division))
        .routes(routes!(sic_division_v3))
        .routes(routes!(sic_industry))
        .routes(routes!(sic_industry_v3))
        .routes(routes!(sic_major))
        .routes(routes!(sic_major_v3))
        // Global/unified SIC search (sic-global-search.md) - fans out
        // across every registered classification system
        .routes(routes!(sic_description_global))
        .routes(routes!(sic_description_global_v3))
        // US SIC similarity, V4-only (sec5.1) - no V3 equivalent
        .routes(routes!(sic_similarity))
        .routes(routes!(sic_similarity_check))
        // Semantic SIC search, global/multi-system (sic-global-search.md)
        .routes(routes!(sic_similarity_global))
        .routes(routes!(sic_hybrid_global))
        .routes(routes!(sic_match))
        .routes(routes!(sic_map))
        // EDGAR, V3 parity (sec5.3/5.4) + V3.0 aliases
        .routes(routes!(edgar_ciks))
        .routes(routes!(edgar_ciks_v3))
        .routes(routes!(edgar_detail))
        .routes(routes!(edgar_detail_v3))
        .routes(routes!(edgar_summary))
        .routes(routes!(edgar_summary_v3))
        .routes(routes!(edgar_firmographics))
        .routes(routes!(edgar_firmographics_v3))
        // Wikipedia (sec8.1) + merged firmographics (sec8.2) + V3.0 aliases
        .routes(routes!(wikipedia_firmographics))
        .routes(routes!(wikipedia_firmographics_v3))
        .routes(routes!(merged_firmographics))
        .routes(routes!(merged_firmographics_v3))
        .layer(axum::middleware::from_fn_with_state(
            tiered_limiter_state,
            tiered_rate_limit,
        ));

    let (router, api) = OpenApiRouter::with_openapi(ApiDoc::openapi())
        .merge(data_router)
        .merge(health_router)
        .merge(sql_router)
        .with_state(state)
        .split_for_parts();

    let app = router
        // docs/plans/v4-release-to-staging.md step 2: the base layout drops Swagger's standalone top
        // bar and logo (the white theme stays). persist_authorization keeps a pasted Basic credential
        // across a reload, which makes the experimental SQL endpoint easy to try from /docs.
        .merge(SwaggerUi::new("/docs").url("/openapi.json", api.clone()).config(
            Config::default()
                .use_base_layout()
                .persist_authorization(true)
                .display_request_duration(true),
        ))
        // Our copy of utoipa-redoc's template (redoc.html): pinned to a light colour scheme (the default
        // page was unreadable under a dark system theme; both /docs and /redoc stay light) and with
        // nothing loaded from a third party: the Redoc script is vendored and served by docs::router(),
        // and the page uses the system font stack (no CDN, no Google Fonts).
        .merge(Redoc::with_url("/redoc", api).custom_html(docs::REDOC_HTML))
        .merge(docs::router())
        // docs/plans/company-dns-ux.md §7/§10: the UX spike - V3's
        // `html/` app plus the similarity-search UI ported forward from
        // `experiments/ic-similarity-service`, served at /ui/ so it
        // can't collide with the API's own path namespace or /docs.
        // Static files only, not behind the data-endpoint rate limiter
        // (the UI's own fetch() calls to /V4.0/... still go through
        // it). Mounted twice at the same directory: /ui (the page
        // itself) and /static (every asset reference inside it -
        // ported unchanged from V3's `html/index.html`, which already
        // hardcodes `/static/...` absolute paths).
        // No Cache-Control from ServeDir by default means only
        // Last-Modified goes out, which lets browsers apply heuristic
        // freshness and silently keep serving a stale index.html/JS
        // for tens of minutes after an edit - with no 304 even hit, so
        // nothing shows up in network logs as "cached" either. Spent a
        // long debugging session chasing a phantom logic bug that was
        // actually just this. `no-cache` still lets the browser keep a
        // local copy, it just forces a conditional GET (If-Modified-
        // Since) on every load, so an edit is never more than one
        // revalidation away from showing up.
        .nest_service(
            "/ui",
            ServiceBuilder::new()
                .layer(SetResponseHeaderLayer::overriding(
                    axum::http::header::CACHE_CONTROL,
                    axum::http::HeaderValue::from_static("no-cache"),
                ))
                .service(ServeDir::new("static")),
        )
        .nest_service(
            "/static",
            ServiceBuilder::new()
                .layer(SetResponseHeaderLayer::overriding(
                    axum::http::header::CACHE_CONTROL,
                    axum::http::HeaderValue::from_static("no-cache"),
                ))
                .service(ServeDir::new("static")),
        )
        // docs/plans/v4-security-hardening.md sec3.3/sec5 step 3: cheap
        // tower-http hygiene, applied to every route including /health
        // and the docs routes (unlike the rate limiter, none of these
        // are gate-shaped - a timeout/body-limit/trace layer being
        // universal is exactly the point).
        .fallback(|| async {
            envelope::not_found(
                "router",
                "No route matches this path. See /docs for the full API.",
            )
        })
        .layer(TraceLayer::new_for_http())
        .layer(TimeoutLayer::with_status_code(
            axum::http::StatusCode::REQUEST_TIMEOUT,
            Duration::from_secs(30),
        ))
        .layer(RequestBodyLimitLayer::new(64 * 1024))
        .layer(CorsLayer::permissive());

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(4000);
    // 0.0.0.0, not 127.0.0.1: k8s/prod/deployment.yaml's liveness/
    // readiness probes and Traefik-forwarded traffic both reach this
    // process via the pod's real network interface, not loopback - a
    // server bound only to 127.0.0.1 inside a pod is unreachable from
    // outside that single network namespace, which would make every
    // probe and every real request fail in that deployment even though
    // this exact setup already works for local `cargo run` (curl from
    // the same machine hits loopback either way).
    let listener = tokio::net::TcpListener::bind(("0.0.0.0", port)).await?;
    tracing::info!("company-dns V4 prototype listening on http://0.0.0.0:{port}");
    tracing::info!(
        "API docs: http://127.0.0.1:{port}/docs (Swagger) http://127.0.0.1:{port}/redoc (ReDoc)"
    );
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await?;

    Ok(())
}

#[utoipa::path(
    get,
    path = "/health",
    responses((status = 200, description = "Liveness - process is up")),
    tag = "System"
)]
async fn health() -> impl IntoResponse {
    axum::Json(json!({
        "status": "healthy",
        "version": "4.0.0",
        "timestamp": chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
    }))
}

// -------------------------------------------------------------- //
// US SIC, V3 parity

async fn sic_description_impl(state: &AppState, sic_desc: &str) -> axum::response::Response {
    match state.sic.find_by_description(sic_desc).await {
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

#[utoipa::path(
    get,
    path = "/V4.0/na/sic/description/{sic_desc}",
    params(("sic_desc" = String, Path, description = "SIC description search term")),
    responses((status = 200, description = "SIC matches", body = ApiEnvelope)),
    tag = "SIC (V4.0)"
)]
async fn sic_description(
    State(state): State<Arc<AppState>>,
    Path(sic_desc): Path<String>,
) -> impl IntoResponse {
    sic_description_impl(&state, &sic_desc).await
}

#[utoipa::path(
    get,
    path = "/V3.0/na/sic/description/{sic_desc}",
    params(("sic_desc" = String, Path, description = "SIC description search term")),
    responses((status = 200, description = "SIC matches", body = ApiEnvelope)),
    tag = "SIC (V3.0, alias)"
)]
async fn sic_description_v3(
    State(state): State<Arc<AppState>>,
    Path(sic_desc): Path<String>,
) -> impl IntoResponse {
    sic_description_impl(&state, &sic_desc).await
}

async fn sic_code_impl(state: &AppState, sic_code: &str) -> axum::response::Response {
    match state.sic.find_by_code(sic_code).await {
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

#[utoipa::path(
    get,
    path = "/V4.0/na/sic/code/{sic_code}",
    params(("sic_code" = String, Path, description = "SIC numeric code")),
    responses((status = 200, description = "SIC matches", body = ApiEnvelope)),
    tag = "SIC (V4.0)"
)]
async fn sic_code(
    State(state): State<Arc<AppState>>,
    Path(sic_code): Path<String>,
) -> impl IntoResponse {
    sic_code_impl(&state, &sic_code).await
}

#[utoipa::path(
    get,
    path = "/V3.0/na/sic/code/{sic_code}",
    params(("sic_code" = String, Path, description = "SIC numeric code")),
    responses((status = 200, description = "SIC matches", body = ApiEnvelope)),
    tag = "SIC (V3.0, alias)"
)]
async fn sic_code_v3(
    State(state): State<Arc<AppState>>,
    Path(sic_code): Path<String>,
) -> impl IntoResponse {
    sic_code_impl(&state, &sic_code).await
}

async fn sic_division_impl(state: &AppState, division_code: &str) -> axum::response::Response {
    match state.sic.find_division(division_code).await {
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

#[utoipa::path(
    get,
    path = "/V4.0/na/sic/division/{division_code}",
    params(("division_code" = String, Path, description = "SIC division code")),
    responses((status = 200, description = "Division matches", body = ApiEnvelope)),
    tag = "SIC (V4.0)"
)]
async fn sic_division(
    State(state): State<Arc<AppState>>,
    Path(division_code): Path<String>,
) -> impl IntoResponse {
    sic_division_impl(&state, &division_code).await
}

#[utoipa::path(
    get,
    path = "/V3.0/na/sic/division/{division_code}",
    params(("division_code" = String, Path, description = "SIC division code")),
    responses((status = 200, description = "Division matches", body = ApiEnvelope)),
    tag = "SIC (V3.0, alias)"
)]
async fn sic_division_v3(
    State(state): State<Arc<AppState>>,
    Path(division_code): Path<String>,
) -> impl IntoResponse {
    sic_division_impl(&state, &division_code).await
}

async fn sic_industry_impl(state: &AppState, industry_code: &str) -> axum::response::Response {
    match state.sic.find_industry_group(industry_code).await {
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

#[utoipa::path(
    get,
    path = "/V4.0/na/sic/industry/{industry_code}",
    params(("industry_code" = String, Path, description = "SIC industry-group code")),
    responses((status = 200, description = "Industry-group matches", body = ApiEnvelope)),
    tag = "SIC (V4.0)"
)]
async fn sic_industry(
    State(state): State<Arc<AppState>>,
    Path(industry_code): Path<String>,
) -> impl IntoResponse {
    sic_industry_impl(&state, &industry_code).await
}

#[utoipa::path(
    get,
    path = "/V3.0/na/sic/industry/{industry_code}",
    params(("industry_code" = String, Path, description = "SIC industry-group code")),
    responses((status = 200, description = "Industry-group matches", body = ApiEnvelope)),
    tag = "SIC (V3.0, alias)"
)]
async fn sic_industry_v3(
    State(state): State<Arc<AppState>>,
    Path(industry_code): Path<String>,
) -> impl IntoResponse {
    sic_industry_impl(&state, &industry_code).await
}

async fn sic_major_impl(state: &AppState, major_code: &str) -> axum::response::Response {
    match state.sic.find_major_group(major_code).await {
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

#[utoipa::path(
    get,
    path = "/V4.0/na/sic/major/{major_code}",
    params(("major_code" = String, Path, description = "SIC major-group code")),
    responses((status = 200, description = "Major-group matches", body = ApiEnvelope)),
    tag = "SIC (V4.0)"
)]
async fn sic_major(
    State(state): State<Arc<AppState>>,
    Path(major_code): Path<String>,
) -> impl IntoResponse {
    sic_major_impl(&state, &major_code).await
}

#[utoipa::path(
    get,
    path = "/V3.0/na/sic/major/{major_code}",
    params(("major_code" = String, Path, description = "SIC major-group code")),
    responses((status = 200, description = "Major-group matches", body = ApiEnvelope)),
    tag = "SIC (V3.0, alias)"
)]
async fn sic_major_v3(
    State(state): State<Arc<AppState>>,
    Path(major_code): Path<String>,
) -> impl IntoResponse {
    sic_major_impl(&state, &major_code).await
}

// -------------------------------------------------------------- //
// Global/unified SIC search - fans out across every classification
// system registered on `state.sic` (today: US SIC, and Japan SIC once
// its data file is available - `main()`'s startup, below). V3 parity:
// `GET /V3.0/global/sic/description/{query_string}` ->
// `UnifiedSICQueries.search_all_descriptions` (`lib/unified_sic.py`).
// `docs/plans/sic-global-search.md` - keyword variant only for now;
// semantic/hybrid global are explicitly deferred there.

async fn sic_description_global_impl(state: &AppState, query: &str) -> axum::response::Response {
    match state.sic.find_by_description_global(query).await {
        Ok(matches) if !matches.is_empty() => ok(
            "SicCatalog->find_by_description_global",
            format!("{} SIC matches for [{query}] across all systems", matches.len()),
            json!(matches),
        )
        .into_response(),
        Ok(_) => not_found(
            "SicCatalog->find_by_description_global",
            format!("No SIC found for description [{query}] in any registered system"),
        )
        .into_response(),
        Err(e) => {
            server_error("SicCatalog->find_by_description_global", e.to_string()).into_response()
        }
    }
}

#[utoipa::path(
    get,
    path = "/V4.0/global/sic/description/{query}",
    params(("query" = String, Path, description = "SIC description search term, matched across every registered classification system")),
    responses((status = 200, description = "SIC matches across all systems, each tagged with source_type", body = ApiEnvelope)),
    tag = "SIC Global (V4.0)"
)]
async fn sic_description_global(
    State(state): State<Arc<AppState>>,
    Path(query): Path<String>,
) -> impl IntoResponse {
    sic_description_global_impl(&state, &query).await
}

#[utoipa::path(
    get,
    path = "/V3.0/global/sic/description/{query_string}",
    params(("query_string" = String, Path, description = "SIC description search term, matched across every registered classification system")),
    responses((status = 200, description = "SIC matches across all systems, each tagged with source_type", body = ApiEnvelope)),
    tag = "SIC Global (V3.0, alias)"
)]
async fn sic_description_global_v3(
    State(state): State<Arc<AppState>>,
    Path(query_string): Path<String>,
) -> impl IntoResponse {
    sic_description_global_impl(&state, &query_string).await
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

#[utoipa::path(
    get,
    path = "/V4.0/na/sic/similarity/{query}",
    params(
        ("query" = String, Path, description = "Free-text query to embed and search"),
        ("k" = Option<usize>, Query, description = "Number of results, 1-50 (default 10)"),
        ("model" = Option<String>, Query, description = "Embedding model (default all_minilm_l6_v2)"),
    ),
    responses((status = 200, description = "Nearest SIC entries by embedding distance", body = ApiEnvelope)),
    tag = "SIC Similarity (V4.0-only)"
)]
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
// Semantic SIC search, global/multi-system - second of
// docs/plans/sic-global-search.md's three global variants (keyword
// built first, hybrid still open). V4-only, no V3 equivalent - same as
// single-system Semantic search above, V3 never had this capability at
// all, global or otherwise.

#[utoipa::path(
    get,
    path = "/V4.0/global/sic/similarity/{query}",
    params(
        ("query" = String, Path, description = "Free-text query to embed and search, across every registered classification system"),
        ("k" = Option<usize>, Query, description = "Number of results, 1-50 (default 10)"),
        ("model" = Option<String>, Query, description = "Embedding model (default all_minilm_l6_v2)"),
    ),
    responses((status = 200, description = "Nearest SIC entries by embedding distance across all systems, each tagged with source_type", body = ApiEnvelope)),
    tag = "SIC Similarity Global (V4.0-only)"
)]
async fn sic_similarity_global(
    State(state): State<Arc<AppState>>,
    Path(query): Path<String>,
    Query(params): Query<SimilarityParams>,
) -> impl IntoResponse {
    if model_info(&params.model).is_none() {
        return server_error(
            "SicCatalog->search_similar_global",
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
                return server_error("SicCatalog->search_similar_global", e.to_string())
                    .into_response()
            }
        }
    };

    match state
        .sic
        .search_similar_global(&params.model, &vector, k)
        .await
    {
        Ok(hits) => ok(
            "SicCatalog->search_similar_global",
            format!("{} similar SIC entries for [{query}] across all systems", hits.len()),
            json!(hits),
        )
        .into_response(),
        Err(e) => server_error("SicCatalog->search_similar_global", e.to_string()).into_response(),
    }
}

// -------------------------------------------------------------- //
// Hybrid (keyword + semantic, Reciprocal Rank Fusion) SIC search across
// every registered system - docs/plans/sic-hybrid-search.md. V4-only, no V3
// equivalent, global only (no per-region variant).

#[utoipa::path(
    get,
    path = "/V4.0/global/sic/hybrid/{query}",
    params(
        ("query" = String, Path, description = "Free-text query: matched as a case-insensitive substring of class descriptions (keyword engine) and embedded (semantic engine), the two ranked lists fused with Reciprocal Rank Fusion, across every registered classification system"),
        ("k" = Option<usize>, Query, description = "Number of results, 1-50 (default 10)"),
        ("model" = Option<String>, Query, description = "Embedding model (default all_minilm_l6_v2)"),
    ),
    responses((status = 200, description = "Fused SIC entries across all systems, each tagged with source_type, keyword_rank / semantic_rank (null when that engine did not find it), rrf_score and, when found semantically, the raw cosine similarity", body = ApiEnvelope)),
    tag = "SIC Hybrid Global (V4.0-only)"
)]
async fn sic_hybrid_global(
    State(state): State<Arc<AppState>>,
    Path(query): Path<String>,
    Query(params): Query<SimilarityParams>,
) -> impl IntoResponse {
    if model_info(&params.model).is_none() {
        return server_error(
            "SicCatalog->search_hybrid_global",
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
                return server_error("SicCatalog->search_hybrid_global", e.to_string())
                    .into_response()
            }
        }
    };

    match state
        .sic
        .search_hybrid_global(&params.model, &query, &vector, k)
        .await
    {
        Ok(hits) => ok(
            "SicCatalog->search_hybrid_global",
            format!("{} hybrid SIC entries for [{query}] across all systems", hits.len()),
            json!(hits),
        )
        .into_response(),
        Err(e) => server_error("SicCatalog->search_hybrid_global", e.to_string()).into_response(),
    }
}

// -------------------------------------------------------------- //
// Company description -> a recommended SET of industry codes per system
// (docs/plans/company-sic-match.md). V4-only, and the first POST route: a
// description of 100-650 tokens does not belong in a URL path. Chunked
// (sentence windows of about 128 word pieces) because the model reads only
// 256 and a long description is several businesses, not one. No LLM.

// ---- EXPERIMENTAL: SQL endpoint (docs/plans/v4-sql-endpoint.md) ----

#[utoipa::path(
    post,
    path = "/V4.0/sql",
    request_body = sql_endpoint::SqlRequest,
    security(("basic_auth" = [])),
    responses(
        (status = 200, description = "Columns and rows (explicit nulls), with the row cap applied and stated limitations", body = ApiEnvelope),
        (status = 400, description = "Unknown dataset, empty SQL, SQL that does not parse, or a statement that is not a single read-only query", body = ApiEnvelope),
        (status = 401, description = "No or wrong HTTP Basic credentials", body = ApiEnvelope),
        (status = 403, description = "The profile is not granted SQL, or not that dataset", body = ApiEnvelope),
        (status = 422, description = "The query needed more memory than the pool allows", body = ApiEnvelope),
        (status = 429, description = "Too many SQL queries running, or too many failed logins", body = ApiEnvelope),
        (status = 504, description = "The statement hit the timeout and was cancelled", body = ApiEnvelope),
    ),
    tag = "experimental",
    summary = "Experimental: run one read-only SQL statement against a dataset",
    description = "EXPERIMENTAL: may change or be removed without notice. Off unless the operator sets COMPANY_DNS_SQL_ENABLED. Needs HTTP Basic Auth (profile id and token) from the operator's credentials file, and a profile with SQL access in the rules. One read-only statement per request against dataset `sic` or `edgar`, in DataFusion's SQL dialect; embedding columns are not exposed; rows, time and memory are capped. `select * from information_schema.columns` lists tables and columns."
)]
async fn sql_query(
    State(state): State<Arc<AppState>>,
    axum::extract::ConnectInfo(peer): axum::extract::ConnectInfo<SocketAddr>,
    headers: axum::http::HeaderMap,
    axum::Json(req): axum::Json<sql_endpoint::SqlRequest>,
) -> axum::response::Response {
    match &state.sql {
        Some(sql) => sql.handle(peer, &headers, req).await,
        None => not_found(sql_endpoint::MODULE, "The SQL endpoint is not enabled on this server.").into_response(),
    }
}


#[derive(Deserialize, utoipa::ToSchema)]
struct MatchRequest {
    /// The company description (pasted, or fetched from the Wikipedia/merged
    /// endpoint by the caller). Up to about 30 KB. Ignored when `chunks` is given.
    #[serde(default)]
    text: String,
    /// Optional: already-split segments to match as they are (the stepper's
    /// "re-match with the segments I kept"). Nothing is re-chunked.
    #[serde(default)]
    chunks: Vec<String>,
    /// Which classification systems to match against, by label ("US SIC",
    /// "ISIC", "EU NACE", "Japan SIC"). Default: US SIC only; the other systems
    /// are reached by mapping the chosen codes (`/V4.0/global/sic/map`).
    #[serde(default = "default_match_systems")]
    systems: Vec<String>,
    #[serde(default = "default_model")]
    model: String,
}

fn default_match_systems() -> Vec<String> {
    vec![company_match::US.to_string()]
}

const MATCH_MAX_CHARS: usize = 30_000;

#[utoipa::path(
    post,
    path = "/V4.0/global/sic/match",
    request_body = MatchRequest,
    responses(
        (status = 200, description = "For every registered classification system: 2-5 recommended codes with their hierarchy and the chunk that supports each, plus alternatives; the chunks; and stated limitations", body = ApiEnvelope),
        (status = 400, description = "Empty or too-long text, or unknown model", body = ApiEnvelope),
    ),
    tag = "SIC Company Match (V4.0-only)"
)]
async fn sic_match(
    State(state): State<Arc<AppState>>,
    axum::Json(req): axum::Json<MatchRequest>,
) -> axum::response::Response {
    const MODULE: &str = "SicCatalog->match_company";
    if model_info(&req.model).is_none() {
        return bad_request(MODULE, format!("unknown model: {}", req.model)).into_response();
    }
    if req.chunks.is_empty() && req.text.trim().is_empty() {
        return bad_request(MODULE, "text is empty").into_response();
    }
    if req.text.chars().count() + req.chunks.iter().map(|c| c.chars().count()).sum::<usize>() > MATCH_MAX_CHARS {
        return bad_request(MODULE, format!("text is longer than {MATCH_MAX_CHARS} characters")).into_response();
    }

    // Tokenise, chunk and embed under the embedder lock; search after releasing it.
    let (prepared, vectors) = {
        let mut embedders = state.embedders.lock().await;
        let prepared = match if req.chunks.is_empty() {
            embedders.prepare_text(&req.model, &req.text)
        } else {
            embedders.prepare_chunks(&req.model, &req.chunks)
        } {
            Ok(p) => p,
            Err(e) => return server_error(MODULE, e.to_string()).into_response(),
        };
        if prepared.chunks.is_empty() {
            return bad_request(MODULE, "text has no content").into_response();
        }
        if prepared.chunks.len() > company_match::MAX_CHUNKS {
            return bad_request(
                MODULE,
                format!(
                    "text is too long: {} chunks (limit {}); use the company's own summary paragraphs",
                    prepared.chunks.len(),
                    company_match::MAX_CHUNKS
                ),
            )
            .into_response();
        }
        let texts: Vec<String> = prepared
            .chunks
            .iter()
            .map(|c| prepared.text[c.span.start..c.span.end].to_string())
            .collect();
        // chunks and key phrases embedded together, one batch
        let mut all = texts;
        all.extend(prepared.phrases.iter().cloned());
        match embedders.embed_batch(&req.model, &all) {
            Ok(v) => (prepared, v),
            Err(e) => return server_error(MODULE, e.to_string()).into_response(),
        }
    };

    let n_chunks = prepared.chunks.len();
    let mut per_chunk = Vec::with_capacity(n_chunks);
    for v in &vectors[..n_chunks] {
        match state.sic.search_systems(&req.model, v, Some(&req.systems), None, company_match::POOL_PER_SYSTEM).await {
            Ok(hits) => per_chunk.push(hits),
            Err(e) => return server_error(MODULE, e.to_string()).into_response(),
        }
    }
    let mut per_phrase = Vec::with_capacity(prepared.phrases.len());
    for (text, v) in prepared.phrases.iter().zip(&vectors[n_chunks..]) {
        match state.sic.search_systems(&req.model, v, Some(&req.systems), None, 1).await {
            Ok(hits) => per_phrase.push((text.clone(), hits)),
            Err(e) => return server_error(MODULE, e.to_string()).into_response(),
        }
    }
    let systems = company_match::choose(&per_chunk, &per_phrase);

    let mut limitations = vec![
        json!({"code": "suggestion_not_a_decision", "message": "These are ranked suggestions from how the text reads, not a determination of the company's classification."}),
        json!({"code": "english_only", "message": "Matching uses an English model against English labels; non-English text is not supported."}),
        json!({"code": "no_judgement_of_primary_business", "message": "The method cannot tell a company's main business from a side line; votes and similarity are only proxies."}),
    ];
    if prepared.total_tokens < company_match::SHORT_INPUT_BELOW {
        limitations.push(json!({"code": "short_input", "message": "Very little text was given; add more of the company's description for a meaningful result."}));
    }
    for s in &systems {
        let top = s.recommended.iter().map(|e| e.similarity).fold(f32::MIN, f32::max);
        if top < company_match::WEAK_MATCH_BELOW {
            limitations.push(json!({"code": "weak_match", "system": s.system, "message": format!("Nothing in {} matched this text closely.", s.system)}));
        }
    }

    // Each chunk's own three best codes per system (the reading view shows
    // what each segment, on its own, points at).
    let chunks: Vec<_> = prepared
        .chunks
        .iter()
        .enumerate()
        .map(|(i, c)| {
            let mut top = serde_json::Map::new();
            for hit in &per_chunk[i] {
                let list = top.entry(hit.system.clone()).or_insert_with(|| json!([]));
                if let Some(arr) = list.as_array_mut() {
                    if arr.len() < 3 {
                        arr.push(json!({
                            "code": hit.levels.last().map(|l| l.id.as_str()).unwrap_or(""),
                            "title": hit.levels.last().map(|l| l.description.as_str()).unwrap_or(""),
                            "similarity": hit.similarity,
                        }));
                    }
                }
            }
            json!({
                "index": i,
                "text": &prepared.text[c.span.start..c.span.end],
                "tokens": c.tokens,
                "model_window": prepared.window_of(c),
                "top": top,
            })
        })
        .collect();
    ok(
        MODULE,
        format!("{} chunk(s) matched against {} system(s)", chunks.len(), systems.len()),
        json!({
            "input": {
                "text": prepared.text,
                "tokens": prepared.total_tokens,
                "chunks": chunks.len(),
                "chunk_target_tokens": company_match::CHUNK_TARGET,
                "truncated_without_chunking": prepared.truncation_at.is_some(),
                "phrases": prepared.phrases,
            },
            "chunks": chunks,
            "systems": systems,
            "limitations": limitations,
        }),
    )
    .into_response()
}

// -------------------------------------------------------------- //
// Map a chosen set of codes in one system into others
// (docs/plans/company-sic-match.md sec. 11). By embedding similarity between
// the chosen codes and each target system (no crosswalk tables are used);
// ranked by fit to the description when one is given.
// With no description this is a plain code-to-code lookup.

#[derive(Deserialize, utoipa::ToSchema)]
struct MapRequest {
    /// The system the codes belong to: "US SIC", "ISIC", "EU NACE" or "Japan SIC".
    from: String,
    /// Class ids in `from` (e.g. "3571", "2620", "26.20").
    codes: Vec<String>,
    /// Target systems by label; default: every other system.
    #[serde(default)]
    to: Vec<String>,
    /// Optional company description, used to rank the candidates.
    #[serde(default)]
    description: String,
    #[serde(default = "default_model")]
    model: String,
}

const KNOWN_SYSTEMS: [&str; 4] = [company_match::US, company_match::ISIC, company_match::NACE, company_match::JAPAN];

#[utoipa::path(
    post,
    path = "/V4.0/global/sic/map",
    request_body = MapRequest,
    responses(
        (status = 200, description = "For each target system: recommended codes (up to 5) and alternatives, each with its hierarchy and the source codes it came from", body = ApiEnvelope),
        (status = 400, description = "Unknown system, no codes, or too many codes", body = ApiEnvelope),
    ),
    tag = "SIC Map (V4.0-only)"
)]
async fn sic_map(
    State(state): State<Arc<AppState>>,
    axum::Json(req): axum::Json<MapRequest>,
) -> axum::response::Response {
    const MODULE: &str = "SicCatalog->map_codes";
    if model_info(&req.model).is_none() {
        return bad_request(MODULE, format!("unknown model: {}", req.model)).into_response();
    }
    if !KNOWN_SYSTEMS.contains(&req.from.as_str()) {
        return bad_request(MODULE, format!("unknown system: {} (use one of {})", req.from, KNOWN_SYSTEMS.join(", "))).into_response();
    }
    if req.codes.is_empty() || req.codes.len() > 20 {
        return bad_request(MODULE, "give between 1 and 20 codes").into_response();
    }
    let to: Vec<String> = if req.to.is_empty() {
        KNOWN_SYSTEMS.iter().filter(|s| **s != req.from).map(|s| s.to_string()).collect()
    } else {
        req.to.clone()
    };
    if let Some(bad) = to.iter().find(|t| !KNOWN_SYSTEMS.contains(&t.as_str())) {
        return bad_request(MODULE, format!("unknown target system: {bad}")).into_response();
    }
    if req.description.chars().count() > MATCH_MAX_CHARS {
        return bad_request(MODULE, format!("description is longer than {MATCH_MAX_CHARS} characters")).into_response();
    }

    // Embed the description's chunks when there is one (under the embedder lock).
    let vectors: Vec<Vec<f32>> = if req.description.trim().is_empty() {
        Vec::new()
    } else {
        let mut embedders = state.embedders.lock().await;
        let prepared = match embedders.prepare_text(&req.model, &req.description) {
            Ok(p) => p,
            Err(e) => return server_error(MODULE, e.to_string()).into_response(),
        };
        if prepared.chunks.len() > company_match::MAX_CHUNKS {
            return bad_request(MODULE, format!("description is too long: {} chunks (limit {})", prepared.chunks.len(), company_match::MAX_CHUNKS)).into_response();
        }
        let texts: Vec<String> = prepared.chunks.iter().map(|c| prepared.text[c.span.start..c.span.end].to_string()).collect();
        match embedders.embed_batch(&req.model, &texts) {
            Ok(v) => v,
            Err(e) => return server_error(MODULE, e.to_string()).into_response(),
        }
    };

    match state.sic.map_codes(&req.model, &req.from, &req.codes, &to, &vectors).await {
        Ok(targets) => {
            let limitations = vec![
                json!({"code": "by_similarity", "message": "Matches in other systems are found by how similar the code descriptions read, not from an official correspondence table. Treat them as suggestions and check them."}),
                json!({"code": "suggestion_not_a_decision", "message": "These are ranked suggestions, not a determination of the company's classification."}),
            ];
            ok(
                MODULE,
                format!("{} code(s) in {} mapped into {} system(s)", req.codes.len(), req.from, targets.len()),
                json!({"from": req.from, "codes": req.codes, "used_description": !vectors.is_empty(), "targets": targets, "limitations": limitations}),
            )
            .into_response()
        }
        Err(e) => server_error(MODULE, e.to_string()).into_response(),
    }
}

/// `docs/plans/company-dns-ux.md` §4/§10.2: the live, input-layer
/// truncation check `ic-similarity-service`'s UI validated (fires as
/// the user types, before they search, per direct feedback that a
/// post-search warning is "too late in the process"). Query-string
/// only, no path component, so it can't collide with
/// `/V4.0/na/sic/similarity/{query}` at the router level. Tokenize-
/// only, no embed/search - cheap enough to call on every keystroke
/// pause.
#[derive(Deserialize)]
struct TokenCountParams {
    q: String,
    #[serde(default = "default_model")]
    model: String,
}

#[utoipa::path(
    get,
    path = "/V4.0/na/sic/similarity-check",
    params(
        ("q" = String, Query, description = "Text to tokenize (not embedded or searched)"),
        ("model" = Option<String>, Query, description = "Embedding model (default all_minilm_l6_v2)"),
    ),
    responses((status = 200, description = "Real token count against the model's own tokenizer", body = ApiEnvelope)),
    tag = "SIC Similarity (V4.0-only)"
)]
async fn sic_similarity_check(
    State(state): State<Arc<AppState>>,
    Query(params): Query<TokenCountParams>,
) -> impl IntoResponse {
    if model_info(&params.model).is_none() {
        return server_error(
            "SicCatalog->token_info",
            format!("unknown model: {}", params.model),
        )
        .into_response();
    }

    let embedders = state.embedders.lock().await;
    match embedders.token_info(&params.model, &params.q) {
        Ok(info) => ok(
            "SicCatalog->token_info",
            "token count",
            json!({
                "actual_tokens": info.actual_tokens,
                "max_tokens": info.max_tokens,
                "truncated": info.truncated(),
            }),
        )
        .into_response(),
        Err(e) => server_error("SicCatalog->token_info", e.to_string()).into_response(),
    }
}

// -------------------------------------------------------------- //
// EDGAR, V3 parity

async fn edgar_ciks_impl(state: &AppState, company_name: &str) -> axum::response::Response {
    let Some(catalog) = &state.edgar_catalog else {
        return server_error(
            "EdgarCatalog->find_by_name",
            "EDGAR catalog not loaded - run `cargo run --bin ingest-edgar` first",
        )
        .into_response();
    };
    match catalog.find_by_name(company_name).await {
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

#[utoipa::path(
    get,
    path = "/V4.0/na/companies/edgar/ciks/{company_name}",
    params(("company_name" = String, Path, description = "Company name (fuzzy match)")),
    responses((status = 200, description = "CIK matches", body = ApiEnvelope)),
    tag = "EDGAR (V4.0)"
)]
async fn edgar_ciks(
    State(state): State<Arc<AppState>>,
    Path(company_name): Path<String>,
) -> impl IntoResponse {
    edgar_ciks_impl(&state, &company_name).await
}

#[utoipa::path(
    get,
    path = "/V3.0/na/companies/edgar/ciks/{company_name}",
    params(("company_name" = String, Path, description = "Company name (fuzzy match)")),
    responses((status = 200, description = "CIK matches", body = ApiEnvelope)),
    tag = "EDGAR (V3.0, alias)"
)]
async fn edgar_ciks_v3(
    State(state): State<Arc<AppState>>,
    Path(company_name): Path<String>,
) -> impl IntoResponse {
    edgar_ciks_impl(&state, &company_name).await
}

/// V3's `EdgarQueries.get_all_details(firmographics=True)` - the same
/// method `edgar_summary` calls with `firmographics=False`. Groups
/// matching filings by company (`EdgarCatalog::find_grouped_by_name`,
/// same grouping V3's own loop does) and, for every matched company,
/// merges in a real, cached live `edgarkit` firmographics fetch
/// (`EdgarClient::get_firmographics` - `go-duckdb-rewrite.md` §5.1's
/// cache) in place of the bare `{cik, companyName}` V3 seeds before
/// overwriting it with the same live call. **Decided
/// (2026-09-28): parity with V3 matters more than the extra live calls
/// this costs per unique matched company** - not deferring this the
/// way an earlier draft of this endpoint did.
#[utoipa::path(
    get,
    path = "/V4.0/na/companies/edgar/detail/{company_name}",
    params(("company_name" = String, Path, description = "Company name (fuzzy match)")),
    responses((status = 200, description = "Grouped filings with live firmographics", body = ApiEnvelope)),
    tag = "EDGAR (V4.0)"
)]
async fn edgar_detail(
    State(state): State<Arc<AppState>>,
    Path(company_name): Path<String>,
) -> impl IntoResponse {
    edgar_grouped_response(&state, &company_name, true).await
}

#[utoipa::path(
    get,
    path = "/V3.0/na/companies/edgar/detail/{company_name}",
    params(("company_name" = String, Path, description = "Company name (fuzzy match)")),
    responses((status = 200, description = "Grouped filings with live firmographics", body = ApiEnvelope)),
    tag = "EDGAR (V3.0, alias)"
)]
async fn edgar_detail_v3(
    State(state): State<Arc<AppState>>,
    Path(company_name): Path<String>,
) -> impl IntoResponse {
    edgar_grouped_response(&state, &company_name, true).await
}

/// V3's `get_all_details(firmographics=False)` - same grouping as
/// `edgar_detail`, no live firmographics call, just `{cik,
/// companyName, forms}` per matched company - a cheap, catalog-only
/// name search.
#[utoipa::path(
    get,
    path = "/V4.0/na/companies/edgar/summary/{company_name}",
    params(("company_name" = String, Path, description = "Company name (fuzzy match)")),
    responses((status = 200, description = "Grouped filings, catalog-only", body = ApiEnvelope)),
    tag = "EDGAR (V4.0)"
)]
async fn edgar_summary(
    State(state): State<Arc<AppState>>,
    Path(company_name): Path<String>,
) -> impl IntoResponse {
    edgar_grouped_response(&state, &company_name, false).await
}

#[utoipa::path(
    get,
    path = "/V3.0/na/companies/edgar/summary/{company_name}",
    params(("company_name" = String, Path, description = "Company name (fuzzy match)")),
    responses((status = 200, description = "Grouped filings, catalog-only", body = ApiEnvelope)),
    tag = "EDGAR (V3.0, alias)"
)]
async fn edgar_summary_v3(
    State(state): State<Arc<AppState>>,
    Path(company_name): Path<String>,
) -> impl IntoResponse {
    edgar_grouped_response(&state, &company_name, false).await
}

async fn edgar_grouped_response(
    state: &Arc<AppState>,
    company_name: &str,
    with_firmographics: bool,
) -> axum::response::Response {
    let module = if with_firmographics {
        "EdgarCatalog->find_grouped_by_name(firmographics=true)"
    } else {
        "EdgarCatalog->find_grouped_by_name(firmographics=false)"
    };
    let Some(catalog) = &state.edgar_catalog else {
        return server_error(
            module,
            "EDGAR catalog not loaded - run `cargo run --bin ingest-edgar` first",
        )
        .into_response();
    };
    let groups = match catalog.find_grouped_by_name(company_name).await {
        Ok(g) if !g.is_empty() => g,
        Ok(_) => {
            return not_found(module, format!("No company found for [{company_name}]"))
                .into_response()
        }
        Err(e) => return server_error(module, e.to_string()).into_response(),
    };

    // Same shape as V3's tmp_companies dict: company_name -> company
    // info (bare {cik, companyName} for summary, full live firmographics
    // for detail) with a "forms" field attached either way.
    let mut companies = serde_json::Map::new();
    for group in &groups {
        let mut company_info = if with_firmographics {
            match state.edgar_client.get_firmographics(group.cik).await {
                Ok(fg) => (*fg).clone(),
                // A catalog match with no live firmographics available
                // (e.g. a transient EDGAR error) still gets a real
                // entry, not a dropped company - same bare fallback
                // shape V3 starts from before its own live call.
                Err(_) => json!({
                    "cik": group.cik.to_string(),
                    "companyName": group.company_name,
                }),
            }
        } else {
            json!({
                "cik": group.cik.to_string(),
                "companyName": group.company_name,
            })
        };
        company_info["forms"] = json!(group.forms);
        companies.insert(group.company_name.clone(), company_info);
    }

    ok(
        module,
        format!("{} companies found for [{company_name}]", companies.len()),
        json!({ "companies": companies, "totalCompanies": companies.len() }),
    )
    .into_response()
}

async fn edgar_firmographics_impl(state: &AppState, cik_no: &str) -> axum::response::Response {
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

#[utoipa::path(
    get,
    path = "/V4.0/na/company/edgar/firmographics/{cik_no}",
    params(("cik_no" = String, Path, description = "SEC EDGAR Central Index Key")),
    responses((status = 200, description = "Live EDGAR firmographics", body = ApiEnvelope)),
    tag = "EDGAR (V4.0)"
)]
async fn edgar_firmographics(
    State(state): State<Arc<AppState>>,
    Path(cik_no): Path<String>,
) -> impl IntoResponse {
    edgar_firmographics_impl(&state, &cik_no).await
}

#[utoipa::path(
    get,
    path = "/V3.0/na/company/edgar/firmographics/{cik_no}",
    params(("cik_no" = String, Path, description = "SEC EDGAR Central Index Key")),
    responses((status = 200, description = "Live EDGAR firmographics", body = ApiEnvelope)),
    tag = "EDGAR (V3.0, alias)"
)]
async fn edgar_firmographics_v3(
    State(state): State<Arc<AppState>>,
    Path(cik_no): Path<String>,
) -> impl IntoResponse {
    edgar_firmographics_impl(&state, &cik_no).await
}

// -------------------------------------------------------------- //
// Wikipedia (sec8.1, built 2026-09-28) + merged firmographics (sec8.2)

async fn wikipedia_firmographics_impl(
    state: &AppState,
    company_name: &str,
) -> axum::response::Response {
    let module = "WikipediaClient->get_firmographics";
    match state.wikipedia.get_firmographics(company_name).await {
        Ok(data) => ok(module, "ok", (*data).clone()).into_response(),
        // NotFound carries V3's own hint message verbatim (byte-identical
        // to lib/wikipedia_v2.py's lookup_error, restored here after
        // confirming V3's own custom 404 handler silently discards it -
        // docs/plans/v4-server-prototype.md sec8.1); Request is a real
        // network/parse failure, mapped to 500 instead of 404 so a
        // caller can tell "this company doesn't exist" apart from
        // "Wikipedia/Wikidata was unreachable."
        Err(e) => match e.as_ref() {
            WikipediaError::NotFound(msg) => not_found(module, msg.clone()).into_response(),
            WikipediaError::Request(_) => server_error(module, e.to_string()).into_response(),
        },
    }
}

#[utoipa::path(
    get,
    path = "/V4.0/global/company/wikipedia/firmographics/{company_name}",
    params(("company_name" = String, Path, description = "Company name (near-exact Wikipedia page title, or V3's corporate-suffix hint)")),
    responses((status = 200, description = "Wikipedia/Wikidata firmographics", body = ApiEnvelope)),
    tag = "Wikipedia (V4.0)"
)]
async fn wikipedia_firmographics(
    Path(company_name): Path<String>,
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    wikipedia_firmographics_impl(&state, &company_name).await
}

#[utoipa::path(
    get,
    path = "/V3.0/global/company/wikipedia/firmographics/{company_name}",
    params(("company_name" = String, Path, description = "Company name (near-exact Wikipedia page title, or V3's corporate-suffix hint)")),
    responses((status = 200, description = "Wikipedia/Wikidata firmographics", body = ApiEnvelope)),
    tag = "Wikipedia (V3.0, alias)"
)]
async fn wikipedia_firmographics_v3(
    Path(company_name): Path<String>,
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    wikipedia_firmographics_impl(&state, &company_name).await
}

async fn merged_firmographics_impl(
    state: &AppState,
    company_name: &str,
) -> axum::response::Response {
    // Wikipedia first, as V3's `merge_data` does: its record carries the
    // company's CIK, which is the durable key for finding that company in
    // EDGAR. (A name substring search over the catalog merged unrelated
    // companies in - "Apple" -> "PINEAPPLE EXPRESS CANNABIS Co" - and
    // missed ones whose EDGAR name differs from the query - "IBM".)
    let wikipedia_result = state
        .wikipedia
        .get_firmographics(company_name)
        .await
        .map(|data| (*data).clone())
        .map_err(|e| e.to_string());
    let wiki_cik = wikipedia_result
        .as_ref()
        .ok()
        .and_then(company_dns_firmographics::cik_from_wikipedia);

    let mut lookup = company_dns_firmographics::EdgarLookup {
        wiki_cik,
        catalog_loaded: state.edgar_catalog.is_some(),
        ..Default::default()
    };
    let mut edgar_data = None;
    if let Some(catalog) = &state.edgar_catalog {
        if let Some(cik) = wiki_cik {
            if let Ok(entries) = catalog.find_by_cik(cik).await {
                if !entries.is_empty() {
                    lookup.matched_by = Some("cik");
                    edgar_data = Some(json!(entries));
                }
            }
        } else if let Ok(entries) = catalog.find_by_name(company_name).await {
            // No usable CIK from Wikipedia (the page has none, or there is no
            // page): fall back to the name, but only whole leading words
            // ("apple" -> "APPLE INC", never "PINEAPPLE ..."), and only when
            // that picks out a single company - otherwise say so and leave
            // the EDGAR side out rather than guess.
            let entries: Vec<_> = entries
                .into_iter()
                .filter(|e| company_dns_firmographics::name_matches(&e.company_name, company_name))
                .collect();
            let distinct: std::collections::BTreeSet<u64> = entries.iter().map(|e| e.cik).collect();
            lookup.ambiguous_companies = distinct.len();
            if distinct.len() == 1 {
                lookup.matched_by = Some("name");
                edgar_data = Some(json!(entries));
            }
        }
    }

    let merged = company_dns_firmographics::merge(company_name, edgar_data, wikipedia_result, &lookup);
    ok(
        "merge",
        format!("Merged firmographics for [{company_name}]"),
        merged,
    )
    .into_response()
}

#[utoipa::path(
    get,
    path = "/V4.0/global/company/merged/firmographics/{company_name}",
    params(("company_name" = String, Path, description = "Company name")),
    responses((status = 200, description = "EDGAR + Wikipedia merged firmographics", body = ApiEnvelope)),
    tag = "Merged (V4.0)"
)]
async fn merged_firmographics(
    Path(company_name): Path<String>,
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    merged_firmographics_impl(&state, &company_name).await
}

#[utoipa::path(
    get,
    path = "/V3.0/global/company/merged/firmographics/{company_name}",
    params(("company_name" = String, Path, description = "Company name")),
    responses((status = 200, description = "EDGAR + Wikipedia merged firmographics", body = ApiEnvelope)),
    tag = "Merged (V3.0, alias)"
)]
async fn merged_firmographics_v3(
    Path(company_name): Path<String>,
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    merged_firmographics_impl(&state, &company_name).await
}
