//! CORS policy (`docs/plans/v4-staging-rollout.md`, decision S8).
//!
//! CORS only concerns JavaScript in a web page calling the API from another origin; curl, SDKs,
//! servers and native apps are not affected. The policy has two halves:
//!
//! * **Lookups stay open to any origin**, as in V3 and as `CorsLayer::permissive()` did: the data is
//!   read-only and public, and authentication is a Basic header, not a cookie, so an open policy
//!   exposes no credential.
//! * **The credentialed routes** (`CREDENTIALED_PATHS`: the SQL endpoint) answer cross-origin
//!   requests only for an allow-list. A foreign origin gets no `Access-Control-Allow-Origin`, so the
//!   browser will not hand the page the answer, and its preflight fails.
//!
//! The allow-list is `COMPANY_DNS_CORS_ORIGINS`: a comma-separated list of exact origins
//! (`https://app.example.com`, no path), or `*` to open the credentialed routes too. Unset, it is
//! the same set the rate limiter trusts (`trusted_origin.rs`): mediumroast.io and its subdomains,
//! and localhost on any port.
//!
//! Compared with `permissive()`, an allowed lookup response carries the caller's origin and
//! `Vary: Origin` instead of `*`: the one policy has to tell the two kinds of route apart.

use axum::http::{request::Parts, HeaderValue};
use tower_http::cors::{AllowOrigin, Any, CorsLayer};

use crate::trusted_origin;

/// Paths that take credentials. Keep in step with the `path = ...` of the routes that authenticate
/// (a test checks the SQL path against `main.rs`).
pub const CREDENTIALED_PATHS: &[&str] = &["/V4.0/sql"];

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CredentialedOrigins {
    /// mediumroast.io, its subdomains and localhost (the default).
    Trusted,
    /// Any origin (`*`): the credentialed routes are as open as the lookups.
    Any,
    /// Exactly these origins, lower-cased, without a trailing slash.
    List(Vec<String>),
}

impl CredentialedOrigins {
    /// Parse `COMPANY_DNS_CORS_ORIGINS`. A bad entry is a startup error with a message.
    pub fn parse(value: Option<&str>) -> Result<Self, String> {
        let Some(v) = value.map(str::trim).filter(|v| !v.is_empty()) else {
            return Ok(Self::Trusted);
        };
        let items: Vec<&str> = v.split(',').map(str::trim).filter(|i| !i.is_empty()).collect();
        if items.contains(&"*") {
            return if items.len() == 1 {
                Ok(Self::Any)
            } else {
                Err("COMPANY_DNS_CORS_ORIGINS: \"*\" cannot be combined with other origins".into())
            };
        }
        let mut list = Vec::new();
        for item in items {
            let lower = item.to_ascii_lowercase();
            let rest = lower.strip_prefix("https://").or_else(|| lower.strip_prefix("http://"));
            match rest {
                Some(authority) if !authority.is_empty() && !authority.contains(['/', '?', '#', '@', ' ']) => list.push(lower.clone()),
                _ => return Err(format!(
                    "COMPANY_DNS_CORS_ORIGINS: {item:?} is not an origin; use scheme://host[:port] with no path (for example https://app.example.com), or * for any"
                )),
            }
        }
        Ok(Self::List(list))
    }

    pub fn allows(&self, origin: &str) -> bool {
        match self {
            Self::Trusted => trusted_origin::is_trusted(Some(origin), None),
            Self::Any => true,
            Self::List(list) => list.iter().any(|o| o.eq_ignore_ascii_case(origin)),
        }
    }

    pub fn describe(&self) -> String {
        match self {
            Self::Trusted => "mediumroast.io, its subdomains and localhost".into(),
            Self::Any => "any origin (*)".into(),
            Self::List(list) => list.join(", "),
        }
    }
}

fn is_credentialed(path: &str) -> bool {
    CREDENTIALED_PATHS.iter().any(|p| path == *p || path.strip_prefix(p).is_some_and(|rest| rest.starts_with('/')))
}

/// The layer for the whole application: open for everything except the credentialed paths.
pub fn layer(origins: CredentialedOrigins) -> CorsLayer {
    CorsLayer::new()
        .allow_methods(Any)
        .allow_headers(Any)
        .expose_headers(Any)
        .allow_origin(AllowOrigin::predicate(move |origin: &HeaderValue, parts: &Parts| {
            !is_credentialed(parts.uri.path()) || origin.to_str().is_ok_and(|o| origins.allows(o))
        }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::{header, Method, Request, StatusCode};
    use axum::{routing::{get, post}, Router};
    use tower::ServiceExt;

    fn app(origins: CredentialedOrigins) -> Router {
        Router::new()
            .route("/V3.0/thing", get(|| async { "ok" }))
            .route("/V4.0/sql", post(|| async { "ok" }))
            .layer(layer(origins))
    }

    /// The `Access-Control-Allow-Origin` of a request from `origin`, `None` if the browser would block it.
    async fn allow_origin(app: Router, method: Method, path: &str, origin: &str) -> Option<String> {
        let mut req = Request::builder().method(method.clone()).uri(path).header(header::ORIGIN, origin);
        if method == Method::OPTIONS {
            req = req.header("access-control-request-method", "POST").header("access-control-request-headers", "authorization,content-type");
        }
        let resp = app.oneshot(req.body(Body::empty()).unwrap()).await.unwrap();
        assert!(resp.status() == StatusCode::OK || resp.status() == StatusCode::NO_CONTENT || method != Method::OPTIONS);
        resp.headers().get(header::ACCESS_CONTROL_ALLOW_ORIGIN).map(|v| v.to_str().unwrap().to_string())
    }

    #[tokio::test]
    async fn lookups_answer_any_origin() {
        let a = || app(CredentialedOrigins::Trusted);
        assert_eq!(allow_origin(a(), Method::GET, "/V3.0/thing", "https://partner.example").await.as_deref(), Some("https://partner.example"));
        assert_eq!(allow_origin(a(), Method::OPTIONS, "/V3.0/thing", "https://partner.example").await.as_deref(), Some("https://partner.example"));
    }

    #[tokio::test]
    async fn the_credentialed_route_refuses_a_foreign_origin() {
        let a = || app(CredentialedOrigins::Trusted);
        assert_eq!(allow_origin(a(), Method::POST, "/V4.0/sql", "https://partner.example").await, None);
        assert_eq!(allow_origin(a(), Method::OPTIONS, "/V4.0/sql", "https://partner.example").await, None, "the preflight must fail too");
        assert_eq!(allow_origin(a(), Method::POST, "/V4.0/sql", "https://mediumroast.io.evil.example").await, None, "a lookalike host is not mediumroast.io");
    }

    #[tokio::test]
    async fn the_credentialed_route_answers_the_default_trusted_origins() {
        let a = || app(CredentialedOrigins::Trusted);
        for o in ["https://mediumroast.io", "https://app.mediumroast.io", "http://localhost:5173"] {
            assert_eq!(allow_origin(a(), Method::POST, "/V4.0/sql", o).await.as_deref(), Some(o));
            assert_eq!(allow_origin(a(), Method::OPTIONS, "/V4.0/sql", o).await.as_deref(), Some(o));
        }
    }

    #[tokio::test]
    async fn a_configured_list_replaces_the_default() {
        let list = CredentialedOrigins::parse(Some("https://app.example.com, http://localhost:3000")).unwrap();
        let a = || app(list.clone());
        assert_eq!(allow_origin(a(), Method::POST, "/V4.0/sql", "https://app.example.com").await.as_deref(), Some("https://app.example.com"));
        assert_eq!(allow_origin(a(), Method::POST, "/V4.0/sql", "https://mediumroast.io").await, None, "a list is exact: the default no longer applies");
        assert_eq!(allow_origin(a(), Method::GET, "/V3.0/thing", "https://anyone.example").await.as_deref(), Some("https://anyone.example"), "lookups stay open");
    }

    #[tokio::test]
    async fn star_opens_the_credentialed_route() {
        let a = app(CredentialedOrigins::parse(Some("*")).unwrap());
        assert_eq!(allow_origin(a, Method::POST, "/V4.0/sql", "https://anyone.example").await.as_deref(), Some("https://anyone.example"));
    }

    #[test]
    fn parses_the_setting_and_refuses_nonsense() {
        assert_eq!(CredentialedOrigins::parse(None), Ok(CredentialedOrigins::Trusted));
        assert_eq!(CredentialedOrigins::parse(Some("  ")), Ok(CredentialedOrigins::Trusted));
        assert_eq!(CredentialedOrigins::parse(Some("*")), Ok(CredentialedOrigins::Any));
        assert_eq!(CredentialedOrigins::parse(Some("HTTPS://App.Example.com")).unwrap(), CredentialedOrigins::List(vec!["https://app.example.com".into()]));
        for bad in ["app.example.com", "https://app.example.com/path", "ftp://x", "https://", "*,https://a.example", "https://user@a.example"] {
            assert!(CredentialedOrigins::parse(Some(bad)).unwrap_err().contains("COMPANY_DNS_CORS_ORIGINS"), "{bad}");
        }
    }

    #[test]
    fn credentialed_paths_match_the_route_and_what_is_under_it_only() {
        assert!(is_credentialed("/V4.0/sql"));
        assert!(is_credentialed("/V4.0/sql/anything"));
        assert!(!is_credentialed("/V4.0/sqlx"));
        assert!(!is_credentialed("/V3.0/global/sic/code/1"));
    }

    #[test]
    fn the_credentialed_path_is_the_one_the_server_routes() {
        let main = include_str!("main.rs");
        for p in CREDENTIALED_PATHS {
            assert!(main.contains(&format!("path = \"{p}\"")), "{p} is not a route in main.rs: update CREDENTIALED_PATHS");
        }
    }
}
