//! Rolling shared-secret `User-Agent` trust signal for mediumroast.io -
//! `docs/plans/v4-security-hardening.md` §3.5. Additive to
//! `trusted_origin::is_trusted` (§3.4), not a replacement: this is the
//! only signal that works for a server-to-server call with no
//! `Origin`/`Referer` at all. Promoted from
//! `experiments/rate-limit-spike/src/secret_ua.rs`, unchanged except
//! for how the secret is loaded (§3.5's "fail closed" requirement -
//! see `load_shared_secret` in `main.rs`, not this module).
//!
//! Design: both company_dns and mediumroast.io hold the same shared
//! secret (company_dns's copy sourced from its own K8s Secret via
//! `MEDIUMROAST_SHARED_SECRET`, mediumroast.io's from its Sealed
//! Secret - `docs/plans/v4-deployment.md` covers how that
//! value gets deployed). Neither side ever puts the raw secret on the
//! wire. Instead, each request carries `HMAC-SHA256(secret, salt)` as
//! its `User-Agent`, where `salt` is the current UTC date+hour
//! (`"%Y-%m-%dT%HZ"`, e.g. `"2026-09-29T14Z"`) - a value both sides can
//! compute independently from their own clocks, no coordination
//! needed. company_dns recomputes the expected token for the current
//! hour (and the previous hour, to tolerate a request landing right at
//! an hour boundary where the two clocks briefly disagree) and
//! compares.

use hmac::{Hmac, KeyInit, Mac};
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

/// UTC date+hour salt, e.g. `"2026-09-29T14Z"`. Deterministic from the
/// clock alone - no coordination between company_dns and
/// mediumroast.io beyond both using UTC.
fn salt_for(now: chrono::DateTime<chrono::Utc>) -> String {
    now.format("%Y-%m-%dT%HZ").to_string()
}

fn token_for(secret: &str, salt: &str) -> String {
    let mut mac =
        HmacSha256::new_from_slice(secret.as_bytes()).expect("HMAC accepts any key length");
    mac.update(salt.as_bytes());
    let bytes = mac.finalize().into_bytes();
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Constant-time string comparison for the two hex tokens - both are
/// always 64 hex chars, so the length check itself leaks nothing an
/// attacker doesn't already know.
fn constant_time_eq(a: &str, b: &str) -> bool {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for i in 0..a.len() {
        diff |= a[i] ^ b[i];
    }
    diff == 0
}

/// Trusted if the `User-Agent` header matches `HMAC(secret, salt)` for
/// either the current UTC hour or the one before it (boundary
/// tolerance - see module docs). `secret` is `None` when no shared
/// secret is configured, which disables this bypass entirely (fails
/// closed, never open).
pub fn is_trusted(
    user_agent: Option<&str>,
    secret: Option<&str>,
    now: chrono::DateTime<chrono::Utc>,
) -> bool {
    let (Some(ua), Some(secret)) = (user_agent, secret) else {
        return false;
    };
    let current = token_for(secret, &salt_for(now));
    if constant_time_eq(ua, &current) {
        return true;
    }
    let previous = token_for(secret, &salt_for(now - chrono::Duration::hours(1)));
    constant_time_eq(ua, &previous)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{TimeZone, Utc};

    const SECRET: &str = "mr-io-shared-secret-for-tests-only";

    fn at(y: i32, mo: u32, d: u32, h: u32, mi: u32) -> chrono::DateTime<Utc> {
        Utc.with_ymd_and_hms(y, mo, d, h, mi, 0).unwrap()
    }

    #[test]
    fn salt_is_date_and_hour_only() {
        assert_eq!(salt_for(at(2026, 9, 29, 14, 7)), "2026-09-29T14Z");
        assert_eq!(salt_for(at(2026, 9, 29, 14, 59)), "2026-09-29T14Z");
    }

    #[test]
    fn matching_token_for_current_hour_is_trusted() {
        let now = at(2026, 9, 29, 14, 30);
        let token = token_for(SECRET, &salt_for(now));
        assert!(is_trusted(Some(&token), Some(SECRET), now));
    }

    #[test]
    fn token_from_previous_hour_is_still_trusted_boundary_tolerance() {
        let now = at(2026, 9, 29, 14, 1);
        let previous_hour_token = token_for(SECRET, &salt_for(at(2026, 9, 29, 13, 59)));
        assert!(is_trusted(Some(&previous_hour_token), Some(SECRET), now));
    }

    #[test]
    fn token_from_two_hours_ago_is_rejected() {
        let now = at(2026, 9, 29, 14, 1);
        let stale_token = token_for(SECRET, &salt_for(at(2026, 9, 29, 12, 0)));
        assert!(!is_trusted(Some(&stale_token), Some(SECRET), now));
    }

    #[test]
    fn wrong_secret_is_untrusted() {
        let now = at(2026, 9, 29, 14, 30);
        let token = token_for("a-different-secret", &salt_for(now));
        assert!(!is_trusted(Some(&token), Some(SECRET), now));
    }

    #[test]
    fn no_configured_secret_disables_the_bypass() {
        let now = at(2026, 9, 29, 14, 30);
        let token = token_for(SECRET, &salt_for(now));
        assert!(!is_trusted(Some(&token), None, now));
    }

    #[test]
    fn missing_user_agent_is_untrusted() {
        let now = at(2026, 9, 29, 14, 30);
        assert!(!is_trusted(None, Some(SECRET), now));
    }

    #[test]
    fn garbage_user_agent_is_untrusted() {
        let now = at(2026, 9, 29, 14, 30);
        assert!(!is_trusted(Some("curl/8.7.1"), Some(SECRET), now));
    }
}
