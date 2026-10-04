//! Stateless trusted-origin bypass - `docs/plans/v4-security-hardening.md`
//! §3.4. The local dev site and mediumroast.io should not be
//! rate-limited at all. Both are browser-driven, so they can't be
//! identified by User-Agent (`user_agent::classify` would draconian-
//! tier them same as any other browser) - identified by `Origin`
//! (falling back to `Referer`) instead. Promoted from
//! `experiments/rate-limit-spike/src/trusted_origin.rs`, unchanged.
//!
//! Deliberately parses the header as a URL and compares the *host*,
//! not a substring check - `Origin: https://mediumroast.io.evil.example`
//! must NOT match `mediumroast.io` just because the string appears in
//! it.

const TRUSTED_LOCAL_HOSTS: &[&str] = &["localhost", "127.0.0.1", "::1"];
const TRUSTED_PROD_SUFFIX: &str = "mediumroast.io";

fn host_is_trusted(host: &str) -> bool {
    let host = host.trim_end_matches('.'); // tolerate a trailing-dot FQDN
    if TRUSTED_LOCAL_HOSTS.contains(&host) {
        return true;
    }
    host == TRUSTED_PROD_SUFFIX || host.ends_with(&format!(".{TRUSTED_PROD_SUFFIX}"))
}

fn extract_host(header_value: &str) -> Option<String> {
    let without_scheme = header_value.split("://").nth(1)?;
    let authority = without_scheme
        .split(['/', '?', '#'])
        .next()
        .unwrap_or(without_scheme);
    let host_and_port = authority.rsplit('@').next().unwrap_or(authority);
    let host = if host_and_port.starts_with('[') {
        host_and_port
            .split(']')
            .next()
            .map(|s| s.trim_start_matches('['))?
    } else {
        host_and_port.split(':').next()?
    };
    if host.is_empty() {
        None
    } else {
        Some(host.to_ascii_lowercase())
    }
}

/// `origin` is the `Origin` header value if present; `referer` is the
/// `Referer` header value, checked only when `Origin` is absent
/// (browsers omit `Origin` on some same-origin navigations but usually
/// still send `Referer`).
pub fn is_trusted(origin: Option<&str>, referer: Option<&str>) -> bool {
    let header_value = origin.or(referer);
    match header_value.and_then(extract_host) {
        Some(host) => host_is_trusted(&host),
        None => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn localhost_any_port_is_trusted() {
        assert!(is_trusted(Some("http://localhost:5173"), None));
        assert!(is_trusted(Some("http://localhost:3000"), None));
        assert!(is_trusted(Some("http://127.0.0.1:8080"), None));
        assert!(is_trusted(Some("http://[::1]:9000"), None));
    }

    #[test]
    fn mediumroast_io_and_subdomains_are_trusted() {
        assert!(is_trusted(Some("https://mediumroast.io"), None));
        assert!(is_trusted(Some("https://www.mediumroast.io"), None));
        assert!(is_trusted(Some("https://app.mediumroast.io"), None));
    }

    #[test]
    fn falls_back_to_referer_when_origin_missing() {
        assert!(is_trusted(
            None,
            Some("https://mediumroast.io/some/page?x=1")
        ));
    }

    #[test]
    fn origin_takes_priority_over_referer() {
        assert!(!is_trusted(
            Some("https://evil.example"),
            Some("https://mediumroast.io/")
        ));
    }

    #[test]
    fn lookalike_hosts_are_rejected() {
        assert!(!is_trusted(
            Some("https://mediumroast.io.evil.example"),
            None
        ));
        assert!(!is_trusted(Some("https://notmediumroast.io"), None));
        assert!(!is_trusted(
            Some("https://evil.example/?u=mediumroast.io"),
            None
        ));
        assert!(!is_trusted(Some("https://xlocalhost"), None));
    }

    #[test]
    fn missing_or_unrelated_origin_is_untrusted() {
        assert!(!is_trusted(None, None));
        assert!(!is_trusted(Some("https://example.com"), None));
    }
}
