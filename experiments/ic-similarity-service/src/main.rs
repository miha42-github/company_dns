mod embed;
mod search;

use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Json},
    routing::get,
    Router,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::Mutex;
use tower_http::cors::CorsLayer;
use tower_http::services::ServeDir;

use embed::{model_info, Embedders};
use search::{IcData, SearchHit};

struct AppState {
    data: IcData,
    embedders: Mutex<Embedders>,
    loaded_models: Vec<&'static str>,
}

#[derive(Serialize)]
struct ModelDescriptor {
    id: &'static str,
    label: &'static str,
    dim: usize,
}

#[derive(Deserialize)]
struct SearchParams {
    q: String,
    model: String,
    #[serde(default = "default_k")]
    k: usize,
}

#[derive(Deserialize)]
struct TokenCountParams {
    q: String,
    model: String,
}

/// Real, not estimated - see Embedders::token_info. Confirmed this
/// matters: a 469-token company description against all-MiniLM-L6-v2's
/// 256-token limit silently dropped 213 tokens (45%), including the
/// entire paragraph a human reader would weight most heavily, and it
/// changed the top search result.
#[derive(Serialize)]
struct TruncationInfo {
    actual_tokens: usize,
    max_tokens: usize,
    truncated: bool,
}

#[derive(Serialize)]
struct SearchResponse {
    results: Vec<SearchHit>,
    truncation: TruncationInfo,
}

fn default_k() -> usize {
    10
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let data_path = std::env::var("IC_DATA_PATH")
        .unwrap_or_else(|_| "../../tmp/us_flat_embedded.feather".to_string());

    println!("Loading IC data from {data_path}...");
    let data = IcData::load(&data_path).await?;

    // Default: MiniLM only. go-duckdb-rewrite.md sec7.8 dropped mpnet for
    // IC data - it lost on every quality metric (sec7.6) *and* cost
    // ~484MB extra RSS (~687MB vs ~203MB, measured directly) for no
    // benefit. IC_MODELS=all_mpnet_base_v2 (or "both") still available
    // for comparison if needed.
    let models_to_load: Vec<&'static str> = match std::env::var("IC_MODELS").ok().as_deref() {
        Some("all_mpnet_base_v2") => vec!["all_mpnet_base_v2"],
        Some("both") => vec!["all_minilm_l6_v2", "all_mpnet_base_v2"],
        _ => vec!["all_minilm_l6_v2"], // default
    };
    println!("Loading embedding models: {models_to_load:?}...");
    let embedders = Embedders::load(&models_to_load)?;

    let state = Arc::new(AppState {
        data,
        embedders: Mutex::new(embedders),
        loaded_models: models_to_load,
    });

    let app = Router::new()
        .route("/health", get(health))
        .route("/api/models", get(list_models))
        .route("/api/token-count", get(token_count))
        .route("/api/similar", get(similar))
        .nest_service("/", ServeDir::new("static"))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let listener = tokio::net::TcpListener::bind("127.0.0.1:8080").await?;
    println!("ic-similarity-service listening on http://127.0.0.1:8080");
    axum::serve(listener, app).await?;

    Ok(())
}

async fn health() -> &'static str {
    "ok"
}

async fn list_models(State(state): State<Arc<AppState>>) -> Json<Vec<ModelDescriptor>> {
    let models = state
        .loaded_models
        .iter()
        .filter_map(|id| {
            model_info(id).map(|info| ModelDescriptor {
                id,
                label: info.label,
                dim: info.dim,
            })
        })
        .collect();
    Json(models)
}

/// Input-layer truncation check (moved here per feedback that a
/// post-search warning banner is too late - by then the user has
/// already searched with truncated input). The UI calls this
/// debounced, as the user types/pastes, so the warning shows before
/// they ever hit Search. Tokenize-only, no embed/search - cheap enough
/// to call on every keystroke pause.
async fn token_count(
    State(state): State<Arc<AppState>>,
    Query(params): Query<TokenCountParams>,
) -> impl IntoResponse {
    if model_info(&params.model).is_none() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({ "error": format!("unknown model: {}", params.model) })),
        )
            .into_response();
    }
    let embedders = state.embedders.lock().await;
    match embedders.token_info(&params.model, &params.q) {
        Ok(info) => Json(TruncationInfo {
            actual_tokens: info.actual_tokens,
            max_tokens: info.max_tokens,
            truncated: info.truncated(),
        })
        .into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({ "error": e.to_string() })),
        )
            .into_response(),
    }
}

async fn similar(
    State(state): State<Arc<AppState>>,
    Query(params): Query<SearchParams>,
) -> impl IntoResponse {
    if model_info(&params.model).is_none() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({ "error": format!("unknown model: {}", params.model) })),
        )
            .into_response();
    }
    let k = params.k.clamp(1, 50);

    let (query_vector, truncation) = {
        let mut embedders = state.embedders.lock().await;

        let token_info = match embedders.token_info(&params.model, &params.q) {
            Ok(info) => info,
            Err(e) => {
                return (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({ "error": e.to_string() })),
                )
                    .into_response()
            }
        };
        let truncation = TruncationInfo {
            actual_tokens: token_info.actual_tokens,
            max_tokens: token_info.max_tokens,
            truncated: token_info.truncated(),
        };

        let vector = match embedders.embed_query(&params.model, &params.q) {
            Ok(v) => v,
            Err(e) => {
                return (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({ "error": e.to_string() })),
                )
                    .into_response()
            }
        };
        (vector, truncation)
    };

    match state.data.search(&params.model, &query_vector, k).await {
        Ok(results) => Json(SearchResponse {
            results,
            truncation,
        })
        .into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({ "error": e.to_string() })),
        )
            .into_response(),
    }
}
