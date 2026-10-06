//! Profiles: who is calling, and what are they granted -
//! `docs/plans/v4-sql-endpoint.md` §5a.
//!
//! One file (`COMPANY_DNS_PROFILES_FILE`), a section per profile. A profile has
//! an id, the SHA-256 of its token (never the token), and optional per-feature
//! grants:
//!
//! ```json
//! {"profiles": {
//!   "mediumroast.io": {"secret_sha256": "<hash>",
//!                      "rate_limit": {"bypass": true},
//!                      "sql": {"datasets": ["sic", "edgar"]}},
//!   "partner":        {"secret_sha256": "<hash>",
//!                      "rate_limit": {"requests_per_minute": 600, "burst": 60}}
//! }}
//! ```
//!
//! Callers authenticate with HTTP Basic Auth (profile id and token). Access is a
//! ladder: no credential is anonymous (the rate limiter then tiers by
//! `User-Agent`), a wrong credential is a 401, a right one gets the profile's
//! grants. `Origin`/`Referer` are client-set and are never identity.
//!
//! The file is read once at startup (changing it means a restart) and fails
//! closed: a bad file stops the server.

use axum::{
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use base64::Engine;
use governor::{DefaultKeyedRateLimiter, Quota, RateLimiter};
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeSet, HashMap},
    net::IpAddr,
    num::NonZeroU32,
    path::Path,
};

use crate::envelope::{envelope, too_many_requests};
use crate::sql_endpoint::DATASETS;

const MODULE: &str = "Access->authenticate";
const REALM: &str = "company_dns (experimental)";
/// Failed logins allowed per source IP per minute before further failures get a 429.
pub const FAILED_AUTH_PER_MINUTE: u32 = 10;

// ---------------------------------------------------------------------------
// The profiles file
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProfilesFile {
    profiles: HashMap<String, ProfileEntry>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProfileEntry {
    secret_sha256: String,
    #[serde(default)]
    sql: Option<SqlGrant>,
    #[serde(default)]
    rate_limit: Option<RateLimitEntry>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SqlGrant {
    datasets: Vec<String>,
    #[serde(default)]
    limits: Option<SqlLimitsEntry>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SqlLimitsEntry {
    max_rows: Option<usize>,
    timeout_secs: Option<u64>,
    concurrency: Option<usize>,
    requests_per_minute: Option<u32>,
    burst: Option<u32>,
}

/// A profile's own SQL limits. Every field is optional; what is missing falls back
/// to the server-wide value, and what is set is always clamped by it (a mistake in
/// the file can restrict a profile, never exceed what the host allows).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SqlLimits {
    pub max_rows: Option<usize>,
    pub timeout_secs: Option<u64>,
    pub concurrency: Option<usize>,
    /// Fleet-wide, divided across replicas like the other quotas.
    pub requests_per_minute: Option<u32>,
    pub burst: Option<u32>,
}

/// What a profile's `sql` section grants.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SqlAccess {
    pub datasets: BTreeSet<String>,
    pub limits: SqlLimits,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RateLimitEntry {
    #[serde(default)]
    bypass: bool,
    requests_per_minute: Option<u32>,
    burst: Option<u32>,
}

/// What a profile's `rate_limit` section grants on the lookup routes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RateLimitGrant {
    /// No rate limit at all.
    Bypass,
    /// A quota of its own, replacing the `User-Agent` tiers. Fleet-wide numbers:
    /// the limiter divides them across replicas like the tier quotas.
    Quota { per_minute: u32, burst: u32 },
}

pub struct Profile {
    hash: [u8; 32],
    /// `None`: not granted SQL.
    pub sql: Option<SqlAccess>,
    /// `None`: no grant; an authenticated caller is treated as the normal tier.
    pub rate_limit: Option<RateLimitGrant>,
}

pub struct Profiles {
    by_id: HashMap<String, Profile>,
}

fn decode_hex_32(s: &str) -> Option<[u8; 32]> {
    let s = s.trim();
    if s.len() != 64 || !s.is_ascii() {
        return None;
    }
    let mut out = [0u8; 32];
    for (i, byte) in out.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&s[2 * i..2 * i + 2], 16).ok()?;
    }
    Some(out)
}

/// Constant-time comparison of two digests.
fn digests_equal(a: &[u8; 32], b: &[u8; 32]) -> bool {
    let mut diff = 0u8;
    for i in 0..32 {
        diff |= a[i] ^ b[i];
    }
    diff == 0
}

fn parse_rate_limit(id: &str, entry: RateLimitEntry) -> anyhow::Result<RateLimitGrant> {
    if entry.bypass {
        anyhow::ensure!(
            entry.requests_per_minute.is_none() && entry.burst.is_none(),
            "profile {id:?}: rate_limit.bypass cannot be combined with requests_per_minute or burst"
        );
        return Ok(RateLimitGrant::Bypass);
    }
    let per_minute = entry.requests_per_minute.ok_or_else(|| {
        anyhow::anyhow!("profile {id:?}: rate_limit needs either \"bypass\": true or \"requests_per_minute\"")
    })?;
    anyhow::ensure!(per_minute >= 1, "profile {id:?}: requests_per_minute must be at least 1");
    let burst = entry.burst.unwrap_or(per_minute);
    anyhow::ensure!(burst >= 1, "profile {id:?}: burst must be at least 1");
    Ok(RateLimitGrant::Quota { per_minute, burst })
}

fn parse_sql_limits(id: &str, l: SqlLimitsEntry) -> anyhow::Result<SqlLimits> {
    let positive = |name: &str, v: Option<u64>| -> anyhow::Result<()> {
        anyhow::ensure!(v.is_none_or(|n| n >= 1), "profile {id:?}: sql.limits.{name} must be at least 1");
        Ok(())
    };
    positive("max_rows", l.max_rows.map(|n| n as u64))?;
    positive("timeout_secs", l.timeout_secs)?;
    positive("concurrency", l.concurrency.map(|n| n as u64))?;
    positive("requests_per_minute", l.requests_per_minute.map(u64::from))?;
    positive("burst", l.burst.map(u64::from))?;
    anyhow::ensure!(
        l.burst.is_none() || l.requests_per_minute.is_some(),
        "profile {id:?}: sql.limits.burst needs requests_per_minute"
    );
    Ok(SqlLimits {
        max_rows: l.max_rows,
        timeout_secs: l.timeout_secs,
        concurrency: l.concurrency,
        requests_per_minute: l.requests_per_minute,
        burst: l.burst,
    })
}

impl Profiles {
    pub fn parse(text: &str) -> anyhow::Result<Self> {
        let file: ProfilesFile = serde_json::from_str(text)
            .map_err(|e| anyhow::anyhow!("profiles file is not valid: {e}"))?;
        anyhow::ensure!(!file.profiles.is_empty(), "profiles file has no profiles");
        let mut by_id = HashMap::new();
        for (id, entry) in file.profiles {
            anyhow::ensure!(!id.is_empty() && !id.contains(':'), "profile id {id:?} must be non-empty and contain no ':'");
            let hash = decode_hex_32(&entry.secret_sha256)
                .ok_or_else(|| anyhow::anyhow!("profile {id:?}: secret_sha256 must be 64 hex characters (a SHA-256 of the token)"))?;
            let sql = match entry.sql {
                None => None,
                Some(grant) => {
                    for d in &grant.datasets {
                        anyhow::ensure!(
                            DATASETS.contains(&d.as_str()),
                            "profile {id:?}: unknown dataset {d:?} (known: {})",
                            DATASETS.join(", ")
                        );
                    }
                    let limits = grant.limits.map(|l| parse_sql_limits(&id, l)).transpose()?.unwrap_or_default();
                    Some(SqlAccess { datasets: grant.datasets.into_iter().collect(), limits })
                }
            };
            let rate_limit = entry.rate_limit.map(|r| parse_rate_limit(&id, r)).transpose()?;
            by_id.insert(id, Profile { hash, sql, rate_limit });
        }
        Ok(Self { by_id })
    }

    pub fn load(path: &Path) -> anyhow::Result<Self> {
        let text = std::fs::read_to_string(path)
            .map_err(|e| anyhow::anyhow!("cannot read profiles file {}: {e}", path.display()))?;
        Self::parse(&text).map_err(|e| anyhow::anyhow!("{} ({})", e, path.display()))
    }

    /// Checks `token` against the profile's stored hash in constant time. An
    /// unknown id does the same work against a dummy hash, so response timing does
    /// not say which ids exist.
    fn authenticate(&self, id: &str, token: &str) -> Option<&Profile> {
        let given: [u8; 32] = Sha256::digest(token.as_bytes()).into();
        match self.by_id.get(id) {
            Some(p) => digests_equal(&given, &p.hash).then_some(p),
            None => {
                let _ = digests_equal(&given, &[0u8; 32]);
                None
            }
        }
    }

    pub fn len(&self) -> usize {
        self.by_id.len()
    }

    /// Profiles granted SQL, with what they are granted.
    pub fn sql_grants(&self) -> impl Iterator<Item = (&str, &SqlAccess)> {
        self.by_id.iter().filter_map(|(id, p)| p.sql.as_ref().map(|g| (id.as_str(), g)))
    }

    /// Profile ids with their rate-limit grants (what the limiter builds quotas from).
    pub fn rate_limit_grants(&self) -> impl Iterator<Item = (&str, RateLimitGrant)> {
        self.by_id.iter().filter_map(|(id, p)| p.rate_limit.map(|g| (id.as_str(), g)))
    }

    pub fn ids(&self) -> Vec<String> {
        let mut ids: Vec<String> = self.by_id.keys().cloned().collect();
        ids.sort();
        ids
    }
}

/// `Authorization: Basic base64(id:token)` -> `(id, token)`.
pub fn parse_basic(value: &str) -> Option<(String, String)> {
    let (scheme, rest) = value.trim().split_once(' ')?;
    if !scheme.eq_ignore_ascii_case("basic") {
        return None;
    }
    let bytes = base64::engine::general_purpose::STANDARD.decode(rest.trim()).ok()?;
    let text = String::from_utf8(bytes).ok()?;
    let (id, token) = text.split_once(':')?;
    Some((id.to_string(), token.to_string()))
}

// ---------------------------------------------------------------------------
// Identifying a request
// ---------------------------------------------------------------------------

pub enum Identity<'a> {
    /// No (Basic) credential was sent.
    Anonymous,
    Profile { id: String, profile: &'a Profile },
    /// A credential was sent and was wrong, or too many wrong ones: the response to return.
    Rejected(Response),
}

pub struct Access {
    profiles: Profiles,
    failures: DefaultKeyedRateLimiter<IpAddr>,
}

fn json_response(status: StatusCode, message: &str) -> Response {
    (status, Json(envelope(status.as_u16(), message, MODULE, Value::Null))).into_response()
}

/// 401 with the Basic challenge.
pub fn unauthorized() -> Response {
    let mut response = json_response(
        StatusCode::UNAUTHORIZED,
        "Authentication required: HTTP Basic Auth with a profile id and token.",
    );
    response.headers_mut().insert(
        header::WWW_AUTHENTICATE,
        HeaderValue::from_str(&format!("Basic realm=\"{REALM}\", charset=\"UTF-8\"")).expect("static header value"),
    );
    response
}

impl Access {
    pub fn new(profiles: Profiles) -> Self {
        let quota = Quota::per_minute(NonZeroU32::new(FAILED_AUTH_PER_MINUTE).expect("non-zero"));
        Self { profiles, failures: RateLimiter::keyed(quota) }
    }

    pub fn profiles(&self) -> &Profiles {
        &self.profiles
    }

    fn failed_login(&self, ip: IpAddr, id: &str, why: &str) -> Response {
        tracing::warn!(target: "sql_audit", ip = %ip, profile = id, outcome = why, "authentication failed");
        if let Err(not_until) = self.failures.check_key(&ip) {
            let wait = not_until.wait_time_from(governor::clock::Clock::now(&governor::clock::DefaultClock::default()));
            return too_many_requests(MODULE, "Too many failed authentication attempts.", wait.as_secs().max(1));
        }
        unauthorized()
    }

    /// Who is this request? No `Authorization: Basic` header is anonymous (not an
    /// error: the lookups work without one). A wrong credential is never treated
    /// as anonymous, so a misconfigured integration hears about it at once.
    pub fn identify(&self, headers: &HeaderMap, ip: IpAddr) -> Identity<'_> {
        let Some(auth) = headers.get(header::AUTHORIZATION).and_then(|v| v.to_str().ok()) else {
            return Identity::Anonymous;
        };
        if !auth.trim_start().to_ascii_lowercase().starts_with("basic ") {
            return Identity::Anonymous; // some other scheme: not ours
        }
        let Some((id, token)) = parse_basic(auth) else {
            return Identity::Rejected(self.failed_login(ip, "-", "malformed"));
        };
        match self.profiles.authenticate(&id, &token) {
            Some(profile) => Identity::Profile { id, profile },
            None => Identity::Rejected(self.failed_login(ip, &id, "bad_credentials")),
        }
    }
}

// ---------------------------------------------------------------------------

#[cfg(test)]
pub(crate) mod tests {
    use super::*;

    pub fn token_hash(token: &str) -> String {
        Sha256::digest(token.as_bytes()).iter().map(|b| format!("{b:02x}")).collect()
    }

    #[test]
    fn profiles_parse_and_reject() {
        let h = token_hash("t");
        assert!(Profiles::parse(&format!(r#"{{"profiles": {{"a": {{"secret_sha256": "{h}", "sql": {{"datasets": ["sic","edgar"]}}}}}}}}"#)).is_ok());
        assert!(Profiles::parse("{}").is_err());
        assert!(Profiles::parse(r#"{"profiles": {}}"#).is_err());
        assert!(Profiles::parse(r#"{"profiles": {"a": {"secret_sha256": "short"}}}"#).is_err());
        assert!(Profiles::parse(&format!(r#"{{"profiles": {{"a": {{"secret_sha256": "{h}", "sql": {{"datasets": ["nope"]}}}}}}}}"#)).is_err(), "unknown dataset");
        assert!(Profiles::parse(&format!(r#"{{"profiles": {{"a": {{"secret_sha256": "{h}", "limits": {{}}}}}}}}"#)).is_err(), "unknown keys are errors, not silently ignored");
        assert!(Profiles::parse(&format!(r#"{{"profiles": {{"a:b": {{"secret_sha256": "{h}"}}}}}}"#)).is_err(), "no ':' in an id");
    }

    #[test]
    fn rate_limit_grants_parse() {
        let h = token_hash("t");
        let p = |rl: &str| Profiles::parse(&format!(r#"{{"profiles": {{"a": {{"secret_sha256": "{h}", "rate_limit": {rl}}}}}}}"#));
        let grant = |rl: &str| p(rl).unwrap().by_id["a"].rate_limit.unwrap();
        assert_eq!(grant(r#"{"bypass": true}"#), RateLimitGrant::Bypass);
        assert_eq!(grant(r#"{"requests_per_minute": 600, "burst": 60}"#), RateLimitGrant::Quota { per_minute: 600, burst: 60 });
        assert_eq!(grant(r#"{"requests_per_minute": 40}"#), RateLimitGrant::Quota { per_minute: 40, burst: 40 }, "burst defaults to the rate");
        for bad in [r#"{}"#, r#"{"bypass": false}"#, r#"{"bypass": true, "requests_per_minute": 5}"#, r#"{"requests_per_minute": 0}"#, r#"{"requests_per_minute": 5, "burst": 0}"#, r#"{"bypass": true, "oops": 1}"#] {
            assert!(p(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn sql_limits_parse() {
        let h = token_hash("t");
        let p = |l: &str| Profiles::parse(&format!(r#"{{"profiles": {{"a": {{"secret_sha256": "{h}", "sql": {{"datasets": ["sic"], "limits": {l}}}}}}}}}"#));
        let got = p(r#"{"max_rows": 500, "timeout_secs": 5, "concurrency": 2, "requests_per_minute": 30, "burst": 3}"#).unwrap();
        let lim = got.by_id["a"].sql.as_ref().unwrap().limits;
        assert_eq!(lim, SqlLimits { max_rows: Some(500), timeout_secs: Some(5), concurrency: Some(2), requests_per_minute: Some(30), burst: Some(3) });
        assert_eq!(p("{}").unwrap().by_id["a"].sql.as_ref().unwrap().limits, SqlLimits::default());
        for bad in [r#"{"max_rows": 0}"#, r#"{"timeout_secs": 0}"#, r#"{"concurrency": 0}"#, r#"{"requests_per_minute": 0}"#, r#"{"burst": 5}"#, r#"{"oops": 1}"#] {
            assert!(p(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn basic_header_parsing() {
        let h = base64::engine::general_purpose::STANDARD.encode("id:to:ken");
        assert_eq!(parse_basic(&format!("Basic {h}")), Some(("id".into(), "to:ken".into())));
        assert_eq!(parse_basic(&format!("basic {h}")), Some(("id".into(), "to:ken".into())));
        assert_eq!(parse_basic("Bearer abc"), None);
        assert_eq!(parse_basic("Basic !!!"), None);
        assert_eq!(parse_basic(&format!("Basic {}", base64::engine::general_purpose::STANDARD.encode("nocolon"))), None);
    }

    #[test]
    fn authenticate_checks_the_hash() {
        let h = token_hash("good-token");
        let p = Profiles::parse(&format!(r#"{{"profiles": {{"tester": {{"secret_sha256": "{h}"}}}}}}"#)).unwrap();
        assert!(p.authenticate("tester", "good-token").is_some());
        assert!(p.authenticate("tester", "bad-token").is_none());
        assert!(p.authenticate("nobody", "good-token").is_none());
    }

    fn headers(value: &str) -> HeaderMap {
        let mut h = HeaderMap::new();
        h.insert(header::AUTHORIZATION, HeaderValue::from_str(value).unwrap());
        h
    }

    #[test]
    fn identify_covers_the_four_cases() {
        let h = token_hash("tok");
        let access = Access::new(Profiles::parse(&format!(r#"{{"profiles": {{"p": {{"secret_sha256": "{h}"}}}}}}"#)).unwrap());
        let ip: IpAddr = "10.0.0.9".parse().unwrap();
        let basic = |id: &str, t: &str| format!("Basic {}", base64::engine::general_purpose::STANDARD.encode(format!("{id}:{t}")));

        assert!(matches!(access.identify(&HeaderMap::new(), ip), Identity::Anonymous));
        assert!(matches!(access.identify(&headers("Bearer something"), ip), Identity::Anonymous), "another scheme is not ours");
        assert!(matches!(access.identify(&headers(&basic("p", "tok")), ip), Identity::Profile { .. }));
        assert!(matches!(access.identify(&headers(&basic("p", "nope")), ip), Identity::Rejected(r) if r.status() == StatusCode::UNAUTHORIZED));
        assert!(matches!(access.identify(&headers("Basic !!!"), ip), Identity::Rejected(_)));
    }
}
