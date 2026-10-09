//! Every error the API returns is the JSON envelope - `docs/plans/v4-release-to-staging.md` step 3.
//!
//! Handlers already answer with the envelope, but axum's own rejections (a query parameter that does not
//! parse, a wrong method, a wrong content type, a body over the limit, a timeout) come back with an empty or plain-text body.
//! This layer, outermost, turns those into the same `{code, message, module, data, dependencies}` envelope, keeping
//! the status and every header (`Allow`, `Retry-After`, CORS) and using the original text, if any, as the message.

use crate::envelope::envelope;
use axum::{
    body::{to_bytes, Body},
    http::{header, Request},
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::Value;

pub async fn json_errors(request: Request<Body>, next: Next) -> Response {
    let response = next.run(request).await;
    let status = response.status();
    if !(status.is_client_error() || status.is_server_error()) {
        return response;
    }
    let is_json = response
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.starts_with("application/json"));
    if is_json {
        return response;
    }
    let (parts, body) = response.into_parts();
    let detail = to_bytes(body, 64 * 1024).await.map(|b| String::from_utf8_lossy(&b).trim().to_string()).unwrap_or_default();
    let message = if detail.is_empty() { status.canonical_reason().unwrap_or("error").to_string() } else { detail };
    let mut replaced = (status, Json(envelope(status.as_u16(), message, "router", Value::Null))).into_response();
    for (name, value) in parts.headers.iter() {
        if name != header::CONTENT_TYPE && name != header::CONTENT_LENGTH {
            replaced.headers_mut().append(name.clone(), value.clone());
        }
    }
    replaced
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{http::StatusCode, routing::{get, post}, Router};
    use tower::ServiceExt;

    fn app() -> Router {
        Router::new()
            .route("/ok", get(|| async { "fine" }))
            .route("/empty400", get(|| async { StatusCode::BAD_REQUEST }))
            .route("/text422", get(|| async { (StatusCode::UNPROCESSABLE_ENTITY, "field x is wrong") }))
            .route("/already-json", get(|| async { (StatusCode::NOT_FOUND, Json(serde_json::json!({"code": 404, "message": "mine"}))) }))
            .route("/post-only", post(|| async { "posted" }))
            .layer(axum::middleware::from_fn(json_errors))
    }

    async fn call(method: &str, uri: &str) -> (StatusCode, Option<String>, Option<serde_json::Value>, Response) {
        let r = app().oneshot(Request::builder().method(method).uri(uri).body(Body::empty()).unwrap()).await.unwrap();
        let status = r.status();
        let ct = r.headers().get(header::CONTENT_TYPE).map(|v| v.to_str().unwrap().to_string());
        let bytes = to_bytes(r.into_body(), 1 << 20).await.unwrap();
        let json = serde_json::from_slice(&bytes).ok();
        (status, ct, json, Response::default())
    }

    #[tokio::test]
    async fn success_is_untouched() {
        let (status, ct, json, _) = call("GET", "/ok").await;
        assert_eq!(status, StatusCode::OK);
        assert!(json.is_none(), "plain body kept");
        assert!(ct.is_none_or(|c| !c.starts_with("application/json")));
    }

    #[tokio::test]
    async fn an_empty_error_becomes_an_envelope() {
        let (status, ct, json, _) = call("GET", "/empty400").await;
        assert_eq!(status, StatusCode::BAD_REQUEST);
        assert!(ct.unwrap().starts_with("application/json"));
        let j = json.unwrap();
        assert_eq!((j["code"].as_u64(), j["message"].as_str()), (Some(400), Some("Bad Request")));
        assert_eq!(j["module"], "router");
    }

    #[tokio::test]
    async fn the_original_text_becomes_the_message() {
        let (status, _, json, _) = call("GET", "/text422").await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
        assert_eq!(json.unwrap()["message"], "field x is wrong");
    }

    #[tokio::test]
    async fn a_wrong_method_keeps_its_allow_header() {
        let r = app().oneshot(Request::builder().method("GET").uri("/post-only").body(Body::empty()).unwrap()).await.unwrap();
        assert_eq!(r.status(), StatusCode::METHOD_NOT_ALLOWED);
        assert!(r.headers().get(header::ALLOW).is_some(), "Allow survives the rewrite");
        let j: serde_json::Value = serde_json::from_slice(&to_bytes(r.into_body(), 1 << 20).await.unwrap()).unwrap();
        assert_eq!(j["code"], 405);
    }

    #[tokio::test]
    async fn an_error_that_is_already_json_is_left_alone() {
        let (status, _, json, _) = call("GET", "/already-json").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(json.unwrap()["message"], "mine");
    }
}
