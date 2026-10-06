//! Profiles: who is calling, and what are they granted -
//! `docs/plans/v4-sql-endpoint.md` §5a.
//!
//! Two files, split by what they hold:
//!
//! 1. **Credentials** (`COMPANY_DNS_CREDENTIALS_FILE`), like `/etc/passwd`: one
//!    `profile:sha256-of-token` per line, `#` comments and blank lines allowed. The
//!    only secret file; it holds nothing else.
//!
//!    ```text
//!    # profile : SHA-256 of the token
//!    mediumroast.io:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
//!    partner:60303ae22b998861bce3b28f33eec1be758a213c86c93c076dbe9f558c11c752
//!    ```
//!
//! 2. **Rules** (`COMPANY_DNS_RULES_FILE`, optional), JSON with no secrets in it: a
//!    `defaults` section and per-profile overrides. A profile starts from the
//!    defaults and an override changes only the settings it names (objects merge
//!    key by key; a list or a value replaces; `null` removes an inherited setting).
//!
//!    ```json
//!    {"defaults": {"sql": {"datasets": ["sic"], "limits": {"max_rows": 500}}},
//!     "profiles": {
//!       "mediumroast.io": {"rate_limit": {"bypass": true},
//!                          "sql": {"datasets": ["sic", "edgar"], "limits": {"max_rows": 5000}}},
//!       "partner":        {"rate_limit": {"requests_per_minute": 600}}}}
//!    ```
//!
//! The settings, all optional: `rate_limit` (`{"bypass": true}`, or
//! `{"requests_per_minute", "burst"}`) and `sql` (`datasets` and `limits`). No
//! `rate_limit` means an identified caller on the normal tier; no `sql` means no SQL.
//! Whatever a profile ends up with is clamped by the server-wide limits at the point
//! of use, so these files can restrict a profile but never exceed what the host allows.
//!
//! A profile in the credentials file with no rules entry simply gets the defaults. A
//! rules entry with no credential is an error (it catches typos). Both files are read
//! once at startup and fail closed: a bad file stops the server.
//!
//! Callers authenticate with HTTP Basic Auth (profile id and token). No credential is
//! anonymous (the rate limiter then tiers by `User-Agent`), a wrong one is a 401, a right
//! one gets the profile's settings. `Origin`/`Referer` are client-set and never identity.

use axum::{
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use base64::Engine;
use governor::{DefaultKeyedRateLimiter, Quota, RateLimiter};
use serde::Deserialize;
use serde_json::{Map, Value};
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
// What a profile ends up with
// ---------------------------------------------------------------------------

/// One profile's settings after defaults and overrides are merged.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Rules {
    #[serde(default)]
    rate_limit: Option<RateLimitEntry>,
    #[serde(default)]
    sql: Option<SqlGrant>,
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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RateLimitEntry {
    #[serde(default)]
    bypass: bool,
    requests_per_minute: Option<u32>,
    burst: Option<u32>,
}

/// A profile's own SQL limits. Every field is optional; what is missing falls back
/// to the server-wide value, and what is set is always clamped by it.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SqlLimits {
    pub max_rows: Option<usize>,
    pub timeout_secs: Option<u64>,
    pub concurrency: Option<usize>,
    /// Fleet-wide, divided across replicas like the other quotas.
    pub requests_per_minute: Option<u32>,
    pub burst: Option<u32>,
}

/// What a profile's `sql` setting grants.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SqlAccess {
    pub datasets: BTreeSet<String>,
    pub limits: SqlLimits,
}

/// What a profile's `rate_limit` setting grants on the lookup routes.
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
    /// `None`: no setting; an authenticated caller is treated as the normal tier.
    pub rate_limit: Option<RateLimitGrant>,
}

pub struct Profiles {
    by_id: HashMap<String, Profile>,
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

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

/// `id:sha256hex` per line; `#` comments and blank lines are skipped.
fn parse_credentials(text: &str) -> anyhow::Result<Vec<(String, [u8; 32])>> {
    let mut out: Vec<(String, [u8; 32])> = Vec::new();
    for (n, line) in text.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let n = n + 1;
        let (id, hash) = line
            .split_once(':')
            .ok_or_else(|| anyhow::anyhow!("credentials line {n}: expected profile:sha256 (like /etc/passwd)"))?;
        let id = id.trim();
        anyhow::ensure!(
            !id.is_empty() && !id.chars().any(|c| c.is_whitespace() || c.is_control() || c == ':'),
            "credentials line {n}: profile id {id:?} must be non-empty with no whitespace or ':'"
        );
        let hash = decode_hex_32(hash)
            .ok_or_else(|| anyhow::anyhow!("credentials line {n}: profile {id:?}: the hash must be 64 hex characters (a SHA-256 of the token)"))?;
        anyhow::ensure!(!out.iter().any(|(i, _)| i == id), "credentials line {n}: profile {id:?} appears twice");
        out.push((id.to_string(), hash));
    }
    anyhow::ensure!(!out.is_empty(), "credentials file has no profiles");
    Ok(out)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RulesFile {
    #[serde(default)]
    defaults: Map<String, Value>,
    #[serde(default)]
    profiles: HashMap<String, Map<String, Value>>,
}

/// Merges `over` onto `base`: objects merge key by key, anything else replaces, and a
/// `null` removes the setting (so an override can drop an inherited one).
fn merge(base: &mut Map<String, Value>, over: &Map<String, Value>) {
    for (key, value) in over {
        match value {
            Value::Null => {
                base.remove(key);
            }
            Value::Object(o) => match base.get_mut(key) {
                Some(Value::Object(b)) => merge(b, o),
                _ => {
                    let mut fresh = Map::new();
                    merge(&mut fresh, o);
                    base.insert(key.clone(), Value::Object(fresh));
                }
            },
            other => {
                base.insert(key.clone(), other.clone());
            }
        }
    }
}

/// `bypass` and a quota (`requests_per_minute`/`burst`) are alternatives, so an override of one
/// replaces an inherited other instead of colliding with it: an override with `"bypass": true`
/// drops the inherited quota numbers, and one that sets a quota (without naming `bypass`)
/// drops an inherited bypass. Quota numbers merge with each other as usual, so overriding
/// only `requests_per_minute` keeps an inherited `burst`.
fn reconcile_rate_limit(base: &mut Map<String, Value>, over: &Map<String, Value>) {
    let (Some(Value::Object(o)), Some(Value::Object(b))) = (over.get("rate_limit"), base.get_mut("rate_limit")) else {
        return;
    };
    if o.get("bypass").and_then(Value::as_bool) == Some(true) {
        b.remove("requests_per_minute");
        b.remove("burst");
    } else if !o.contains_key("bypass") && (o.contains_key("requests_per_minute") || o.contains_key("burst")) {
        b.remove("bypass");
    }
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
    /// The credentials text plus the optional rules text. Rules may name only profiles
    /// that have a credential; a profile with no rules entry gets the defaults.
    pub fn from_parts(credentials: &str, rules: Option<&str>) -> anyhow::Result<Self> {
        let creds = parse_credentials(credentials)?;
        let rules: RulesFile = match rules {
            Some(text) => serde_json::from_str(text).map_err(|e| anyhow::anyhow!("rules file is not valid: {e}"))?,
            None => RulesFile { defaults: Map::new(), profiles: HashMap::new() },
        };
        let unknown: Vec<&String> = rules.profiles.keys().filter(|id| !creds.iter().any(|(c, _)| c == *id)).collect();
        anyhow::ensure!(
            unknown.is_empty(),
            "rules name profile(s) with no credential: {} (add them to the credentials file, or fix the name)",
            unknown.iter().map(|s| format!("{s:?}")).collect::<Vec<_>>().join(", ")
        );

        let mut defaults = Map::new();
        merge(&mut defaults, &rules.defaults); // drops nulls in the defaults too
        let mut by_id = HashMap::new();
        for (id, hash) in creds {
            let mut merged = defaults.clone();
            if let Some(over) = rules.profiles.get(&id) {
                reconcile_rate_limit(&mut merged, over);
                merge(&mut merged, over);
            }
            let r: Rules = serde_json::from_value(Value::Object(merged))
                .map_err(|e| anyhow::anyhow!("profile {id:?}: {e}"))?;
            let sql = match r.sql {
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
            let rate_limit = r.rate_limit.map(|r| parse_rate_limit(&id, r)).transpose()?;
            by_id.insert(id, Profile { hash, sql, rate_limit });
        }
        Ok(Self { by_id })
    }

    pub fn load(credentials: &Path, rules: Option<&Path>) -> anyhow::Result<Self> {
        let read = |p: &Path, what: &str| {
            std::fs::read_to_string(p).map_err(|e| anyhow::anyhow!("cannot read {what} file {}: {e}", p.display()))
        };
        let creds = read(credentials, "credentials")?;
        let rules_text = rules.map(|p| read(p, "rules")).transpose()?;
        Self::from_parts(&creds, rules_text.as_deref()).map_err(|e| {
            anyhow::anyhow!(
                "{e} (credentials: {}{})",
                credentials.display(),
                rules.map(|p| format!(", rules: {}", p.display())).unwrap_or_default()
            )
        })
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

    /// Profiles for tests: `creds` are `(id, token)` pairs, `rules` the rules JSON (or none).
    pub fn test_profiles(creds: &[(&str, &str)], rules: Option<&str>) -> Profiles {
        let text: String = creds.iter().map(|(id, t)| format!("{id}:{}\n", token_hash(t))).collect();
        Profiles::from_parts(&text, rules).unwrap()
    }

    fn one(rules: &str) -> anyhow::Result<Profiles> {
        Profiles::from_parts(&format!("a:{}\n", token_hash("t")), Some(rules))
    }

    // --- credentials file ---

    #[test]
    fn credentials_parse_like_passwd() {
        let h = token_hash("t");
        let text = format!("# comment\n\n  alice : {h}  \nbob.example:{h}\n");
        let p = Profiles::from_parts(&text, None).unwrap();
        assert_eq!(p.ids(), vec!["alice".to_string(), "bob.example".to_string()]);
        for bad in ["", "# only a comment\n", "alice\n", "alice:short\n", &format!(":{h}\n"), &format!("a b:{h}\n"), &format!("a:{h}\na:{h}\n"), &format!("a:{}\n", "zz".repeat(32))] {
            assert!(Profiles::from_parts(bad, None).is_err(), "{bad:?}");
        }
    }

    // --- rules: defaults, overrides, inheritance ---

    #[test]
    fn no_rules_means_an_identified_caller_with_no_grants() {
        let p = Profiles::from_parts(&format!("a:{}\n", token_hash("t")), None).unwrap();
        assert!(p.by_id["a"].sql.is_none() && p.by_id["a"].rate_limit.is_none());
    }

    #[test]
    fn a_profile_with_no_override_gets_the_defaults() {
        let h = token_hash("t");
        let p = Profiles::from_parts(
            &format!("a:{h}\nb:{h}\n"),
            Some(r#"{"defaults": {"sql": {"datasets": ["sic"], "limits": {"max_rows": 500}}, "rate_limit": {"requests_per_minute": 100}}}"#),
        )
        .unwrap();
        for id in ["a", "b"] {
            let sql = p.by_id[id].sql.as_ref().unwrap();
            assert_eq!((sql.datasets.len(), sql.limits.max_rows), (1, Some(500)));
            assert_eq!(p.by_id[id].rate_limit, Some(RateLimitGrant::Quota { per_minute: 100, burst: 100 }));
        }
    }

    #[test]
    fn an_override_replaces_only_the_settings_it_names() {
        let h = token_hash("t");
        let p = Profiles::from_parts(
            &format!("a:{h}\nb:{h}\n"),
            Some(r#"{"defaults": {"sql": {"datasets": ["sic"], "limits": {"max_rows": 500, "timeout_secs": 5, "concurrency": 2}},
                                  "rate_limit": {"requests_per_minute": 100, "burst": 10}},
                     "profiles": {"a": {"sql": {"limits": {"max_rows": 9000}}, "rate_limit": {"requests_per_minute": 600}}}}"#),
        )
        .unwrap();
        let a = p.by_id["a"].sql.as_ref().unwrap();
        assert_eq!(a.limits, SqlLimits { max_rows: Some(9000), timeout_secs: Some(5), concurrency: Some(2), ..Default::default() }, "named limit replaced, the rest inherited");
        assert_eq!(a.datasets.iter().collect::<Vec<_>>(), vec!["sic"], "datasets inherited");
        assert_eq!(p.by_id["a"].rate_limit, Some(RateLimitGrant::Quota { per_minute: 600, burst: 10 }), "burst inherited");
        let b = p.by_id["b"].sql.as_ref().unwrap();
        assert_eq!(b.limits.max_rows, Some(500), "the other profile still has the default");
    }

    #[test]
    fn a_list_replaces_and_null_removes_an_inherited_setting() {
        let h = token_hash("t");
        let p = Profiles::from_parts(
            &format!("a:{h}\nb:{h}\nc:{h}\n"),
            Some(r#"{"defaults": {"sql": {"datasets": ["sic"], "limits": {"max_rows": 500, "timeout_secs": 5}}, "rate_limit": {"bypass": true}},
                     "profiles": {"a": {"sql": {"datasets": ["sic", "edgar"]}},
                                  "b": {"sql": null, "rate_limit": null},
                                  "c": {"sql": {"limits": {"max_rows": null}}}}}"#),
        )
        .unwrap();
        assert_eq!(p.by_id["a"].sql.as_ref().unwrap().datasets.len(), 2, "a list replaces, it does not append");
        assert!(p.by_id["b"].sql.is_none() && p.by_id["b"].rate_limit.is_none(), "null removes an inherited setting");
        assert_eq!(p.by_id["c"].sql.as_ref().unwrap().limits, SqlLimits { timeout_secs: Some(5), ..Default::default() }, "null on one limit removes just that one");
        assert_eq!(p.by_id["c"].rate_limit, Some(RateLimitGrant::Bypass));
    }

    #[test]
    fn an_override_can_switch_between_bypass_and_a_quota() {
        let h = token_hash("t");
        let creds = format!("a:{h}\n");
        let grant = |default: &str, over: &str| {
            Profiles::from_parts(&creds, Some(&format!(r#"{{"defaults": {{"rate_limit": {default}}}, "profiles": {{"a": {{"rate_limit": {over}}}}}}}"#)))
                .map(|p| p.by_id["a"].rate_limit)
        };
        // an inherited bypass replaced by a quota, and an inherited quota (with its burst) by a bypass
        assert_eq!(grant(r#"{"bypass": true}"#, r#"{"requests_per_minute": 10}"#).unwrap(), Some(RateLimitGrant::Quota { per_minute: 10, burst: 10 }));
        assert_eq!(grant(r#"{"requests_per_minute": 100, "burst": 7}"#, r#"{"bypass": true}"#).unwrap(), Some(RateLimitGrant::Bypass));
        // quota numbers still merge with each other
        assert_eq!(grant(r#"{"requests_per_minute": 100, "burst": 7}"#, r#"{"requests_per_minute": 300}"#).unwrap(), Some(RateLimitGrant::Quota { per_minute: 300, burst: 7 }));
        // explicit false still works, and a conflict inside one block is still an error
        assert_eq!(grant(r#"{"bypass": true}"#, r#"{"bypass": false, "requests_per_minute": 10}"#).unwrap(), Some(RateLimitGrant::Quota { per_minute: 10, burst: 10 }));
        assert!(Profiles::from_parts(&creds, Some(r#"{"profiles": {"a": {"rate_limit": {"bypass": true, "requests_per_minute": 5}}}}"#)).is_err());
    }

    #[test]
    fn rules_are_validated_strictly() {
        assert!(one(r#"{}"#).is_ok());
        assert!(one(r#"{"oops": 1}"#).is_err(), "unknown top-level key");
        assert!(one(r#"{"defaults": {"oops": 1}}"#).is_err(), "unknown setting in defaults");
        assert!(one(r#"{"profiles": {"a": {"limits": {}}}}"#).is_err(), "unknown setting in an override");
        assert!(one(r#"{"profiles": {"ghost": {}}}"#).is_err(), "rules for a profile with no credential");
        assert!(one(r#"{"profiles": {"a": {"sql": {"datasets": ["nope"]}}}}"#).is_err(), "unknown dataset");
        assert!(one(r#"{"profiles": {"a": {"sql": {"limits": {"max_rows": 5}}}}}"#).is_err(), "sql with no datasets anywhere");
        assert!(one("not json").is_err());
        let msg = one(r#"{"profiles": {"a": {"rate_limit": {"requests_per_minute": "x"}}}}"#).err().unwrap().to_string();
        assert!(msg.contains("\"a\""), "errors name the profile: {msg}");
    }

    #[test]
    fn rate_limit_grants_parse() {
        let grant = |rl: &str| one(&format!(r#"{{"profiles": {{"a": {{"rate_limit": {rl}}}}}}}"#)).map(|p| p.by_id["a"].rate_limit.unwrap());
        assert_eq!(grant(r#"{"bypass": true}"#).unwrap(), RateLimitGrant::Bypass);
        assert_eq!(grant(r#"{"requests_per_minute": 600, "burst": 60}"#).unwrap(), RateLimitGrant::Quota { per_minute: 600, burst: 60 });
        assert_eq!(grant(r#"{"requests_per_minute": 40}"#).unwrap(), RateLimitGrant::Quota { per_minute: 40, burst: 40 }, "burst defaults to the rate");
        for bad in [r#"{}"#, r#"{"bypass": false}"#, r#"{"bypass": true, "requests_per_minute": 5}"#, r#"{"requests_per_minute": 0}"#, r#"{"requests_per_minute": 5, "burst": 0}"#, r#"{"bypass": true, "oops": 1}"#] {
            assert!(grant(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn sql_limits_parse() {
        let limits = |l: &str| one(&format!(r#"{{"profiles": {{"a": {{"sql": {{"datasets": ["sic"], "limits": {l}}}}}}}}}"#)).map(|p| p.by_id["a"].sql.as_ref().unwrap().limits);
        assert_eq!(
            limits(r#"{"max_rows": 500, "timeout_secs": 5, "concurrency": 2, "requests_per_minute": 30, "burst": 3}"#).unwrap(),
            SqlLimits { max_rows: Some(500), timeout_secs: Some(5), concurrency: Some(2), requests_per_minute: Some(30), burst: Some(3) }
        );
        assert_eq!(limits("{}").unwrap(), SqlLimits::default());
        for bad in [r#"{"max_rows": 0}"#, r#"{"timeout_secs": 0}"#, r#"{"concurrency": 0}"#, r#"{"requests_per_minute": 0}"#, r#"{"burst": 5}"#, r#"{"oops": 1}"#] {
            assert!(limits(bad).is_err(), "{bad}");
        }
    }

    // --- Basic Auth ---

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
        let p = test_profiles(&[("tester", "good-token")], None);
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
        let access = Access::new(test_profiles(&[("p", "tok")], None));
        let ip: IpAddr = "10.0.0.9".parse().unwrap();
        let basic = |id: &str, t: &str| format!("Basic {}", base64::engine::general_purpose::STANDARD.encode(format!("{id}:{t}")));

        assert!(matches!(access.identify(&HeaderMap::new(), ip), Identity::Anonymous));
        assert!(matches!(access.identify(&headers("Bearer something"), ip), Identity::Anonymous), "another scheme is not ours");
        assert!(matches!(access.identify(&headers(&basic("p", "tok")), ip), Identity::Profile { .. }));
        assert!(matches!(access.identify(&headers(&basic("p", "nope")), ip), Identity::Rejected(r) if r.status() == StatusCode::UNAUTHORIZED));
        assert!(matches!(access.identify(&headers("Basic !!!"), ip), Identity::Rejected(_)));
    }
}
