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

pub fn server_error(module: &str, message: impl Into<String>) -> impl IntoResponse {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(envelope(500, message, module, json!(null))),
    )
}
