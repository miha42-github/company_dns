//! The API reference pages' own assets - `docs/plans/v4-release-to-staging.md` step 2.
//!
//! `/redoc` used to load its script from `cdn.redoc.ly` (unpinned, so whatever Redocly published next)
//! and its fonts from Google Fonts. That needed internet access in the reader's browser (a blank page on
//! an isolated network) and sent every reader's IP address to Google. Now the Redoc bundle is vendored at a
//! pinned version (`assets/redoc/`, MIT, licences alongside), embedded in the binary and served from here, and
//! the page uses the system font stack. Nothing is fetched from a third party.

use axum::{
    http::{header, HeaderValue},
    response::{IntoResponse, Response},
    routing::get,
    Router,
};

/// The vendored, unmodified Redoc 2.5.4 standalone bundle (MIT; see `assets/redoc/README.md`).
const REDOC_JS: &[u8] = include_bytes!("../assets/redoc/redoc.standalone.js");

/// The `/redoc` page template (utoipa-redoc's default, pinned to a light scheme, no external loads).
pub const REDOC_HTML: &str = include_str!("redoc.html");

/// Where the page's script is served from.
pub const REDOC_JS_PATH: &str = "/redoc/redoc.standalone.js";

async fn redoc_js() -> Response {
    let mut response = REDOC_JS.into_response();
    let headers = response.headers_mut();
    headers.insert(header::CONTENT_TYPE, HeaderValue::from_static("application/javascript; charset=utf-8"));
    // Pinned to one version, so a day of caching is safe; a version change is a new binary.
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("public, max-age=86400"));
    response
}

/// The route for the vendored script. Mounted outside the data routes (like `/docs` and `/redoc`).
pub fn router() -> Router {
    Router::new().route(REDOC_JS_PATH, get(redoc_js))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{body::Body, http::Request, http::StatusCode};
    use sha2::{Digest, Sha256};
    use tower::ServiceExt;

    /// SHA-256 of the vendored bundle (`assets/redoc/README.md`). Changing the file means updating this on purpose.
    const REDOC_JS_SHA256: &str = "dcaf76612bc4a3fbcc923a8966dee2f6146a5f32e5ce1b6f02dd60cbbf89500b";

    #[test]
    fn the_vendored_bundle_is_the_pinned_one() {
        let hash: String = Sha256::digest(REDOC_JS).iter().map(|b| format!("{b:02x}")).collect();
        assert_eq!(hash, REDOC_JS_SHA256, "assets/redoc/redoc.standalone.js changed; update the hash, the README and the notices");
        // the bundle itself says where its licence notices live; they must stay in that file next to it
        assert!(REDOC_JS.starts_with(b"/*! For license information please see redoc.standalone.js.LICENSE.txt */"));
        let notices = std::fs::read_to_string(std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("assets/redoc/redoc.standalone.js.LICENSE.txt")).unwrap();
        assert!(notices.contains("Version: \"2.5.4\""), "the notices belong to the pinned version");
    }

    #[test]
    fn the_licences_ship_with_the_bundle() {
        for f in ["LICENSE", "redoc.standalone.js.LICENSE.txt", "README.md"] {
            let p = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("assets/redoc").join(f);
            assert!(p.exists(), "{} must stay next to the bundle", p.display());
        }
        let mit = std::fs::read_to_string(std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("assets/redoc/LICENSE")).unwrap();
        assert!(mit.contains("MIT License") && mit.contains("Rebilly"));
    }

    #[test]
    fn the_page_loads_nothing_from_a_third_party() {
        assert!(REDOC_HTML.contains("$spec") && REDOC_HTML.contains("$config"), "utoipa-redoc fills these in");
        assert!(REDOC_HTML.contains(REDOC_JS_PATH));
        assert!(REDOC_HTML.contains("color-scheme"));
        let mut markup = String::new();
        let mut in_comment = false;
        for line in REDOC_HTML.lines() {
            if line.contains("<!--") { in_comment = true; }
            if !in_comment { markup.push_str(line); markup.push('\n'); }
            if line.contains("-->") { in_comment = false; }
        }
        for banned in ["cdn.redoc.ly", "googleapis", "gstatic", "http://", "https://"] {
            assert!(!markup.contains(banned), "the template must not reference {banned}");
        }
    }

    #[tokio::test]
    async fn the_script_is_served_with_the_right_headers() {
        let response = router()
            .oneshot(Request::builder().uri(REDOC_JS_PATH).body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers()[header::CONTENT_TYPE], "application/javascript; charset=utf-8");
        assert!(response.headers()[header::CACHE_CONTROL].to_str().unwrap().contains("max-age"));
        let body = axum::body::to_bytes(response.into_body(), 4 * 1024 * 1024).await.unwrap();
        assert_eq!(body.len(), REDOC_JS.len());
    }
}
