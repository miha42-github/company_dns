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
use search::IcData;

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

    let query_vector = {
        let mut embedders = state.embedders.lock().await;
        match embedders.embed_query(&params.model, &params.q) {
            Ok(v) => v,
            Err(e) => {
                return (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({ "error": e.to_string() })),
                )
                    .into_response()
            }
        }
    };

    match state.data.search(&params.model, &query_vector, k).await {
        Ok(hits) => Json(hits).into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({ "error": e.to_string() })),
        )
            .into_response(),
    }
}
