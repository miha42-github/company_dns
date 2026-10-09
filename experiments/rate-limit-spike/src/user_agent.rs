//! Stateless User-Agent classification - `docs/plans/v4-security-hardening.md`
//! §3.1. A pure function of the header value alone: no registry, no
//! per-caller history, nothing persisted across requests.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tier {
    Normal,
    Draconian,
}

/// Default out-of-the-box User-Agent strings of common HTTP client
/// libraries/tools - nobody hand-sets these on purpose, so a request
/// carrying one hasn't actually self-identified. Prefix match, same
/// spirit as V3's `BLOCKED_PATTERNS` (`lib/security_middleware.py:20-51`)
/// but classifying into a rate-limit tier instead of 403-blocking.
const DEFAULT_LIBRARY_PREFIXES: &[&str] = &[
    "curl/",
    "python-requests/",
    "Go-http-client/",
    "okhttp/",
    "axios/",
    "PostmanRuntime/",
    "libwww-perl/",
    "Wget/",
    "python-urllib/",
    "Java/",
];

fn is_default_library_string(ua: &str) -> bool {
    DEFAULT_LIBRARY_PREFIXES.iter().any(|p| ua.starts_with(p)) || ua == "Mozilla/5.0"
}

/// EDGAR-style self-identification bar: *some* way to reach whoever's
/// calling - an email address or a URL - not a specific registered
/// identity.
fn has_contact_signal(ua: &str) -> bool {
    ua.contains('@') || ua.contains("http://") || ua.contains("https://")
}

pub fn classify(user_agent: Option<&str>) -> Tier {
    let ua = match user_agent.map(str::trim) {
        Some(s) if !s.is_empty() => s,
        _ => return Tier::Draconian,
    };
    if is_default_library_string(ua) {
        return Tier::Draconian;
    }
    if !has_contact_signal(ua) {
        return Tier::Draconian;
    }
    Tier::Normal
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_is_draconian() {
        assert_eq!(classify(None), Tier::Draconian);
    }

    #[test]
    fn empty_is_draconian() {
        assert_eq!(classify(Some("")), Tier::Draconian);
        assert_eq!(classify(Some("   ")), Tier::Draconian);
    }

    #[test]
    fn default_library_strings_are_draconian() {
        assert_eq!(classify(Some("curl/8.4.0")), Tier::Draconian);
        assert_eq!(classify(Some("python-requests/2.31.0")), Tier::Draconian);
        assert_eq!(classify(Some("Go-http-client/1.1")), Tier::Draconian);
        assert_eq!(classify(Some("Mozilla/5.0")), Tier::Draconian);
    }

    #[test]
    fn no_contact_signal_is_draconian() {
        // Looks hand-written but gives no way to reach the operator.
        assert_eq!(classify(Some("MyScraperBot/1.0")), Tier::Draconian);
    }

    #[test]
    fn email_contact_is_normal() {
        assert_eq!(
            classify(Some("mediumroast-client/1.0 (hello@mediumroast.io)")),
            Tier::Normal
        );
    }

    #[test]
    fn url_contact_is_normal() {
        assert_eq!(
            classify(Some("SomeBot/2.0 (+https://example.com/bot)")),
            Tier::Normal
        );
    }

    #[test]
    fn browser_ua_without_contact_is_still_draconian() {
        // A real browser UA has neither an email nor a URL in it - by
        // this policy it's draconian too. That's a deliberate v1 choice
        // (§3.1's format check applies uniformly), not an oversight;
        // this API's real callers are expected to be programmatic
        // integrations, not browsers, matching V3's actual usage.
        assert_eq!(
            classify(Some(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )),
            Tier::Draconian
        );
    }
}
