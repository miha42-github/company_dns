//! V3's response envelope (`docs/plans/go-duckdb-rewrite.md` §2,
//! `docs/plans/v4-server-prototype.md` §10): `{code, message, module,
//! data, dependencies}`. **Decided (v4-server-prototype.md §10,
//! 2026-09-28): every V4 endpoint that's a V3-parity replacement keeps
//! this envelope byte-for-byte identical** - the `§7` perf comparison
//! and anything downstream still expecting V3's shape depend on it.
//! `GET /V4.0/na/sic/similarity/{query}` (V4-only, no V3 equivalent)
//! also uses this envelope for now, as the simplest default - not a
//! long-term commitment (§10's breaking-change question for V4-only
//! endpoints is explicitly deferred).

use axum::{http::StatusCode, response::IntoResponse, Json};
use serde_json::{json, Value};
use utoipa::ToSchema;

/// The OpenAPI-facing twin of the envelope this module actually builds
/// (`envelope()`, below) - exists only so `#[utoipa::path(...)]`
/// annotations have a `body = ApiEnvelope` to point at
/// (`docs/plans/v4-openapi-docs.md` §3.1). Handlers keep building
/// `serde_json::Value` via `ok()`/`not_found()`/`server_error()`
/// exactly as before; this type is never constructed at runtime.
///
/// `data`/`dependencies` are untyped `Object` schemas on purpose, not
/// an oversight - checked `lib/models.py` before assuming V4 needed
/// per-endpoint typed schemas: V3's own OpenAPI spec uses the same
/// generic `BaseAPIResponse` class (`data: Dict[str, Any]`) for every
/// single endpoint, so an open object here is real V3 parity, not a
/// simplification (`v4-openapi-docs.md` §1).
#[derive(serde::Serialize, ToSchema)]
pub struct ApiEnvelope {
    /// HTTP status code, duplicated in the body (V3's own convention)
    pub code: u16,
    pub message: String,
    pub module: String,
    #[schema(value_type = Object)]
    pub data: Value,
    #[schema(value_type = Object)]
    pub dependencies: Value,
    /// Present on the Wikipedia answers: what the request cost (`extraction_time`, `parallel_api_time`, `total_time` in seconds,
    /// and V4's `cache_hit`).
    #[serde(skip_serializing_if = "Option::is_none")]
    #[schema(value_type = Option<Object>)]
    pub performance: Option<Value>,
}

pub fn envelope(code: u16, message: impl Into<String>, module: &str, data: Value) -> Value {
    json!({
        "code": code,
        "message": message.into(),
        "module": module,
        "data": data,
        "dependencies": {
            "modules": { "company_dns_v4": "https://github.com/miha42-github/company_dns" }
        }
    })
}

pub fn ok(module: &str, message: impl Into<String>, data: Value) -> impl IntoResponse {
    (StatusCode::OK, Json(envelope(200, message, module, data)))
}

pub fn not_found(module: &str, message: impl Into<String>) -> impl IntoResponse {
    (
        StatusCode::NOT_FOUND,
        Json(envelope(404, message, module, json!(null))),
    )
}

pub fn bad_request(module: &str, message: impl Into<String>) -> impl IntoResponse {
    (
        StatusCode::BAD_REQUEST,
        Json(envelope(400, message, module, json!(null))),
    )
}

pub fn server_error(module: &str, message: impl Into<String>) -> impl IntoResponse {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(envelope(500, message, module, json!(null))),
    )
}

/// `docs/plans/v4-security-hardening.md` §3.2/§5: the rate limiter's
/// 429 response, same `ApiEnvelope` shape as every other error path
/// here, plus a real `Retry-After` header (`governor::NotUntil::
/// wait_time_from(...)`'s output, in seconds - `rate_limit.rs`).
/// Returns a full `Response` rather than `impl IntoResponse` because
/// the header has to be set on the response directly, not expressed
/// through the `(StatusCode, Json<_>)` tuple the other helpers use.
pub fn too_many_requests(
    module: &str,
    message: impl Into<String>,
    retry_after_secs: u64,
) -> axum::response::Response {
    let mut response = (
        StatusCode::TOO_MANY_REQUESTS,
        Json(envelope(429, message, module, json!(null))),
    )
        .into_response();
    if let Ok(value) = axum::http::HeaderValue::from_str(&retry_after_secs.to_string()) {
        response
            .headers_mut()
            .insert(axum::http::header::RETRY_AFTER, value);
    }
    response
}
