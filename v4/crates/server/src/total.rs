//! `total` on every answer (decided 2026-10-11, extended to the V3-shaped paths the same day).
//!
//! Every answer is the JSON envelope `{code, message, module, data, dependencies}`; this layer, applied outermost so it also sees error
//! envelopes, adds one more top-level field, `total`: **how many results `data` holds.** A list gives its length; a V3-shaped dictionary that
//! already counts its results (`data.total`, or EDGAR's `data.totalCompanies`) gives that count; any other single record (a company's firmographics,
//! a match report) gives 1; and `null` (no match, or an error) gives 0. A client can read the count without looking inside `data`, and the same
//! field will carry the full match count once results are paged.
//!
//! One place, rather than every handler, so no current or future route can forget it. On the `/V3.0/`, `/V2.0/` and `/v2/` paths it is the one
//! deliberate, additive difference from V3's exact envelope (recorded in the differences ledger); a client that reads only the fields V3 had
//! is unaffected. It leaves any body that is not an envelope alone (`/health`, the OpenAPI document), and non-JSON (the docs, the UI).

use axum::{
    body::{to_bytes, Body},
    http::{header, Request, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
};
use serde_json::{Number, Value};

/// A generous ceiling for the largest answer (a 10,000-row SQL result is a few MB).
const MAX_BODY_BYTES: usize = 64 * 1024 * 1024;

/// What `total` is for a given `data`.
pub fn total_of(data: &Value) -> u64 {
    match data {
        Value::Array(items) => items.len() as u64,
        Value::Null => 0,
        // V3's dictionaries already say how many results they hold
        Value::Object(map) => ["total", "totalCompanies"].iter().find_map(|k| map.get(*k).and_then(Value::as_u64)).unwrap_or(1),
        _ => 1,
    }
}

/// The envelope with `total` added, or `None` if this body is not an envelope (or already has one).
fn with_total(body: &[u8]) -> Option<Vec<u8>> {
    let mut value: Value = serde_json::from_slice(body).ok()?;
    let object = value.as_object_mut()?;
    if !(object.contains_key("code") && object.contains_key("data")) || object.contains_key("total") {
        return None;
    }
    let total = total_of(&object["data"]);
    object.insert("total".into(), Value::Number(Number::from(total)));
    serde_json::to_vec(&value).ok()
}

pub async fn add_total(request: Request<Body>, next: Next) -> Response {
    let response = next.run(request).await;
    let is_json = response
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.starts_with("application/json"));
    if !is_json {
        return response;
    }
    let (mut parts, body) = response.into_parts();
    let bytes = match to_bytes(body, MAX_BODY_BYTES).await {
        Ok(b) => b,
        Err(_) => return (StatusCode::INTERNAL_SERVER_ERROR, "the response could not be read to add its total").into_response(),
    };
    let out = with_total(&bytes).unwrap_or_else(|| bytes.to_vec());
    parts.headers.remove(header::CONTENT_LENGTH);
    Response::from_parts(parts, Body::from(out))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{http::StatusCode, routing::get, Json, Router};
    use serde_json::json;
    use tower::ServiceExt;

    fn app() -> Router {
        let envelope = |data: Value| Json(json!({"code": 200, "message": "m", "module": "x", "data": data, "dependencies": {}}));
        Router::new()
            .route("/V4.0/list", get(move || async move { envelope(json!([1, 2, 3])) }))
            .route("/V4.0/empty", get(move || async move { envelope(json!([])) }))
            .route("/V4.0/one", get(move || async move { envelope(json!({"cik": 320193})) }))
            .route("/V4.0/none", get(|| async { (StatusCode::NOT_FOUND, Json(json!({"code": 404, "message": "m", "module": "x", "data": null, "dependencies": {}}))) }))
            .route("/V4.0/notenvelope", get(|| async { Json(json!({"hello": "world"})) }))
            .route("/V4.0/text", get(|| async { "plain" }))
            .route("/V3.0/list", get(move || async move { envelope(json!({"sics": [1, 2], "total": 2})) }))
            .route("/V3.0/ciks", get(move || async move { envelope(json!({"companies": ["a"], "totalCompanies": 7})) }))
            .route("/V3.0/record", get(move || async move { envelope(json!({"name": "Apple Inc."})) }))
            .route("/health", get(|| async { Json(json!({"status": "healthy"})) }))
            .layer(axum::middleware::from_fn(add_total))
    }

    async fn fetch(path: &str) -> (StatusCode, Option<String>, Vec<u8>) {
        let resp = app().oneshot(Request::builder().uri(path).body(Body::empty()).unwrap()).await.unwrap();
        let status = resp.status();
        let len = resp.headers().get(header::CONTENT_LENGTH).map(|v| v.to_str().unwrap().to_string());
        let body = to_bytes(resp.into_body(), 1 << 20).await.unwrap().to_vec();
        (status, len, body)
    }

    async fn json_of(path: &str) -> Value {
        serde_json::from_slice(&fetch(path).await.2).unwrap()
    }

    #[tokio::test]
    async fn a_list_gets_its_length() {
        let v = json_of("/V4.0/list").await;
        assert_eq!(v["total"], 3);
        assert_eq!(v["data"], json!([1, 2, 3]), "data itself is untouched");
        assert_eq!(json_of("/V4.0/empty").await["total"], 0);
    }

    #[tokio::test]
    async fn a_single_record_is_one_and_no_match_or_an_error_is_zero() {
        assert_eq!(json_of("/V4.0/one").await["total"], 1);
        let (status, _, body) = fetch("/V4.0/none").await;
        assert_eq!(status, StatusCode::NOT_FOUND, "the status is untouched");
        assert_eq!(serde_json::from_slice::<Value>(&body).unwrap()["total"], 0);
    }

    #[tokio::test]
    async fn the_content_length_matches_the_new_body() {
        let (_, len, body) = fetch("/V4.0/list").await;
        if let Some(len) = len {
            assert_eq!(len.parse::<usize>().unwrap(), body.len());
        }
    }

    #[tokio::test]
    async fn v3_shaped_dictionaries_report_the_count_they_already_carry() {
        let v = json_of("/V3.0/list").await;
        assert_eq!(v["total"], 2);
        assert_eq!(v["data"], json!({"sics": [1, 2], "total": 2}), "V3's data is untouched");
        assert_eq!(json_of("/V3.0/ciks").await["total"], 7, "EDGAR's totalCompanies");
        assert_eq!(json_of("/V3.0/record").await["total"], 1);
    }

    #[tokio::test]
    async fn health_is_not_an_envelope_and_is_left_alone() {
        assert!(json_of("/health").await.get("total").is_none());
    }

    #[tokio::test]
    async fn bodies_that_are_not_envelopes_are_left_alone() {
        assert_eq!(json_of("/V4.0/notenvelope").await, json!({"hello": "world"}));
        assert_eq!(fetch("/V4.0/text").await.2, b"plain");
    }

    #[test]
    fn an_existing_total_is_not_overwritten() {
        assert!(with_total(br#"{"code":200,"data":[],"total":9}"#).is_none());
    }
}
