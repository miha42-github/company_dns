//! EXPERIMENTAL SQL endpoint - `docs/plans/v4-sql-endpoint.md`.
//!
//! `POST /V4.0/sql` runs one read-only SQL statement against one dataset
//! (`sic` or `edgar`). It can use real CPU and memory, so it is closed by
//! default: off unless `COMPANY_DNS_SQL_ENABLED` is set, and every request needs
//! HTTP Basic Auth against the profiles file (`COMPANY_DNS_PROFILES_FILE`), which
//! holds only a SHA-256 of each profile's token. It deliberately ignores
//! `Origin`/`Referer` (client-set, so no proof of identity) and sits outside the
//! tiered rate limiter's bypasses.
//!
//! Phase 1 (this file): one global set of limits for every profile. Per-profile
//! limit overrides are phase 2 of the plan.
//!
//! Each dataset gets its own dedicated query context, separate from the one the
//! other endpoints use: the embedding (`vector_*`) columns are dropped from the
//! views, memory is capped by a pool, spilling to disk is disabled, and
//! parallelism is capped so one query cannot take every core.

use axum::{
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use base64::Engine;
use company_dns_edgar::EdgarCatalog;
use company_dns_sic::SicCatalog;
use datafusion::{
    arrow::json::writer::{JsonArray, WriterBuilder},
    error::DataFusionError,
    execution::{
        disk_manager::{DiskManagerBuilder, DiskManagerMode},
        runtime_env::RuntimeEnvBuilder,
    },
    prelude::{SQLOptions, SessionConfig, SessionContext},
};
use governor::{DefaultKeyedRateLimiter, Quota, RateLimiter};
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeSet, HashMap},
    net::{IpAddr, SocketAddr},
    num::NonZeroU32,
    path::Path,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::Semaphore;

use crate::envelope::{envelope, too_many_requests};

pub const MODULE: &str = "SqlEndpoint->query";
const REALM: &str = "company_dns sql (experimental)";
/// The only datasets there are. A profile naming anything else is a config error.
pub const DATASETS: [&str; 2] = ["sic", "edgar"];
/// Failed logins allowed per source IP per minute before further failures get a 429.
const FAILED_AUTH_PER_MINUTE: u32 = 10;

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/// The one global set of limits (phase 1). Env vars, all optional.
#[derive(Debug, Clone, PartialEq)]
pub struct SqlConfig {
    /// `COMPANY_DNS_SQL_DEFAULT_ROWS` (1000): rows returned when the request gives no `limit`.
    pub default_rows: usize,
    /// `COMPANY_DNS_SQL_MAX_ROWS` (10000): ceiling a request's `limit` is clamped to.
    pub max_rows: usize,
    /// `COMPANY_DNS_SQL_TIMEOUT_SECS` (10): statement timeout.
    pub timeout_secs: u64,
    /// `COMPANY_DNS_SQL_MEMORY_MB` (256): memory pool of each dataset's query context.
    pub memory_mb: usize,
    /// `COMPANY_DNS_SQL_MAX_CONCURRENT` (4): queries running at once on this pod.
    pub max_concurrent: usize,
    /// `COMPANY_DNS_SQL_PARALLELISM` (2): DataFusion partitions per query, so a
    /// query cannot take every core.
    pub parallelism: usize,
}

fn parse_flag(raw: Option<String>) -> anyhow::Result<bool> {
    match raw.as_deref().map(|s| s.trim().to_ascii_lowercase()) {
        None => Ok(false),
        Some(v) if matches!(v.as_str(), "" | "0" | "false" | "no" | "off") => Ok(false),
        Some(v) if matches!(v.as_str(), "1" | "true" | "yes" | "on") => Ok(true),
        Some(v) => anyhow::bail!("COMPANY_DNS_SQL_ENABLED must be true or false, got {v:?}"),
    }
}

fn parse_num(get: &dyn Fn(&str) -> Option<String>, name: &str, default: u64, min: u64) -> anyhow::Result<u64> {
    match get(name).map(|s| s.trim().to_string()).filter(|s| !s.is_empty()) {
        None => Ok(default),
        Some(raw) => {
            let n: u64 = raw
                .parse()
                .map_err(|_| anyhow::anyhow!("{name} must be a whole number, got {raw:?}"))?;
            anyhow::ensure!(n >= min, "{name} must be at least {min}, got {n}");
            Ok(n)
        }
    }
}

impl SqlConfig {
    /// `Ok(None)` when the feature is off (the default); `Err` for a bad value
    /// (startup fails with the message rather than silently falling back).
    pub fn from_lookup(get: &dyn Fn(&str) -> Option<String>) -> anyhow::Result<Option<Self>> {
        if !parse_flag(get("COMPANY_DNS_SQL_ENABLED"))? {
            return Ok(None);
        }
        let default_rows = parse_num(get, "COMPANY_DNS_SQL_DEFAULT_ROWS", 1_000, 1)? as usize;
        let max_rows = parse_num(get, "COMPANY_DNS_SQL_MAX_ROWS", 10_000, 1)? as usize;
        anyhow::ensure!(
            default_rows <= max_rows,
            "COMPANY_DNS_SQL_DEFAULT_ROWS ({default_rows}) cannot exceed COMPANY_DNS_SQL_MAX_ROWS ({max_rows})"
        );
        Ok(Some(Self {
            default_rows,
            max_rows,
            timeout_secs: parse_num(get, "COMPANY_DNS_SQL_TIMEOUT_SECS", 10, 1)?,
            memory_mb: parse_num(get, "COMPANY_DNS_SQL_MEMORY_MB", 256, 16)? as usize,
            max_concurrent: parse_num(get, "COMPANY_DNS_SQL_MAX_CONCURRENT", 4, 1)? as usize,
            parallelism: parse_num(get, "COMPANY_DNS_SQL_PARALLELISM", 2, 1)? as usize,
        }))
    }
}

// ---------------------------------------------------------------------------
// Profiles file and HTTP Basic Auth
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
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SqlGrant {
    datasets: Vec<String>,
}

struct Profile {
    hash: [u8; 32],
    /// `None`: the profile exists but is not granted SQL.
    sql_datasets: Option<BTreeSet<String>>,
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
            let sql_datasets = match entry.sql {
                None => None,
                Some(grant) => {
                    for d in &grant.datasets {
                        anyhow::ensure!(
                            DATASETS.contains(&d.as_str()),
                            "profile {id:?}: unknown dataset {d:?} (known: {})",
                            DATASETS.join(", ")
                        );
                    }
                    Some(grant.datasets.into_iter().collect())
                }
            };
            by_id.insert(id, Profile { hash, sql_datasets });
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
}

/// `Authorization: Basic base64(id:token)` -> `(id, token)`.
fn parse_basic(value: &str) -> Option<(String, String)> {
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
// Query contexts
// ---------------------------------------------------------------------------

/// A dedicated, locked-down query context over `tables` of `source`: the
/// `vector_*` columns removed, a memory pool, no disk spill, capped parallelism.
pub async fn build_query_context(
    source: &SessionContext,
    tables: &[String],
    cfg: &SqlConfig,
) -> anyhow::Result<SessionContext> {
    let runtime = RuntimeEnvBuilder::new()
        .with_memory_limit(cfg.memory_mb * 1024 * 1024, 1.0)
        .with_disk_manager_builder(DiskManagerBuilder::default().with_mode(DiskManagerMode::Disabled))
        .build_arc()?;
    // information_schema lets a caller discover tables and columns with plain SELECTs.
    let config = SessionConfig::new()
        .with_target_partitions(cfg.parallelism)
        .with_information_schema(true);
    let ctx = SessionContext::new_with_config_rt(config, runtime);
    for table in tables {
        let df = source.table(table.as_str()).await?;
        let vectors: Vec<String> = df
            .schema()
            .fields()
            .iter()
            .filter(|f| f.name().starts_with("vector_"))
            .map(|f| f.name().to_string())
            .collect();
        let df = if vectors.is_empty() { df } else { df.drop_columns(&vectors)? };
        ctx.register_table(table.as_str(), df.into_view())?;
    }
    Ok(ctx)
}

// ---------------------------------------------------------------------------
// Running a statement
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub enum QueryError {
    /// Did not parse/plan, or is not a read-only query. The message is DataFusion's.
    Invalid(String),
    Timeout,
    /// Hit the memory pool.
    Resources(String),
    /// Anything else; detail is logged, not returned.
    Failed(String),
}

pub struct QueryOutput {
    pub columns: Vec<(String, String)>,
    pub rows: Vec<Value>,
    pub truncated: bool,
}

fn classify(e: DataFusionError, planning: bool) -> QueryError {
    let msg = e.to_string();
    if msg.contains("Resources exhausted") {
        QueryError::Resources(msg)
    } else if planning {
        QueryError::Invalid(msg)
    } else {
        QueryError::Failed(msg)
    }
}

/// Runs one read-only statement: DDL, DML and statements (SET, COPY, CREATE EXTERNAL
/// TABLE, ...) are refused, more than one statement is refused by DataFusion,
/// at most `limit` rows are returned (one extra is read to know whether the
/// result was cut), and the whole thing is cancelled after `timeout`.
pub async fn execute(
    ctx: &SessionContext,
    sql: &str,
    limit: usize,
    timeout: Duration,
) -> Result<QueryOutput, QueryError> {
    let options = SQLOptions::new()
        .with_allow_ddl(false)
        .with_allow_dml(false)
        .with_allow_statements(false);
    let run = async {
        let df = ctx.sql_with_options(sql, options).await.map_err(|e| classify(e, true))?;
        let df = df.limit(0, Some(limit + 1)).map_err(|e| classify(e, true))?;
        let columns: Vec<(String, String)> = df
            .schema()
            .fields()
            .iter()
            .map(|f| (f.name().to_string(), f.data_type().to_string()))
            .collect();
        let batches = df.collect().await.map_err(|e| classify(e, false))?;

        let mut writer = WriterBuilder::new().with_explicit_nulls(true).build::<_, JsonArray>(Vec::new());
        let refs: Vec<&_> = batches.iter().collect();
        writer.write_batches(&refs).map_err(|e| QueryError::Failed(e.to_string()))?;
        writer.finish().map_err(|e| QueryError::Failed(e.to_string()))?;
        let bytes = writer.into_inner();
        let mut rows: Vec<Value> = if bytes.is_empty() {
            Vec::new()
        } else {
            serde_json::from_slice(&bytes).map_err(|e| QueryError::Failed(e.to_string()))?
        };
        let truncated = rows.len() > limit;
        rows.truncate(limit);
        Ok(QueryOutput { columns, rows, truncated })
    };
    match tokio::time::timeout(timeout, run).await {
        Ok(result) => result,
        Err(_) => Err(QueryError::Timeout),
    }
}

// ---------------------------------------------------------------------------
// Request handling
// ---------------------------------------------------------------------------

#[derive(Deserialize, utoipa::ToSchema)]
pub struct SqlRequest {
    /// `sic` (US SIC plus Japan SIC, EU NACE and ISIC when loaded) or `edgar` (the filings catalog).
    pub dataset: String,
    /// One read-only statement (SELECT, WITH, EXPLAIN). DataFusion SQL dialect.
    pub sql: String,
    /// Rows to return. Defaults to the server's default and is clamped to its ceiling.
    #[serde(default)]
    pub limit: Option<usize>,
}

pub struct SqlState {
    config: SqlConfig,
    profiles: Profiles,
    contexts: HashMap<String, SessionContext>,
    permits: Arc<Semaphore>,
    failures: DefaultKeyedRateLimiter<IpAddr>,
}

fn json_response(status: StatusCode, message: &str, data: Value) -> Response {
    (status, Json(envelope(status.as_u16(), message, MODULE, data))).into_response()
}

fn unauthorized() -> Response {
    let mut response = json_response(
        StatusCode::UNAUTHORIZED,
        "Authentication required: HTTP Basic Auth with a profile id and token.",
        Value::Null,
    );
    response.headers_mut().insert(
        header::WWW_AUTHENTICATE,
        HeaderValue::from_str(&format!("Basic realm=\"{REALM}\", charset=\"UTF-8\"")).expect("static header value"),
    );
    response
}

impl SqlState {
    pub async fn build(
        config: SqlConfig,
        profiles: Profiles,
        sic: &SicCatalog,
        edgar: Option<&EdgarCatalog>,
    ) -> anyhow::Result<Self> {
        let mut contexts = HashMap::new();
        let (source, tables) = sic.query_source();
        contexts.insert("sic".to_string(), build_query_context(&source, &tables, &config).await?);
        match edgar {
            Some(catalog) => {
                let (source, tables) = catalog.query_source();
                contexts.insert("edgar".to_string(), build_query_context(&source, &tables, &config).await?);
            }
            None => tracing::warn!("SQL endpoint: the EDGAR catalog is not loaded, so dataset \"edgar\" is unavailable"),
        }
        Ok(Self::from_parts(config, profiles, contexts))
    }

    fn from_parts(config: SqlConfig, profiles: Profiles, contexts: HashMap<String, SessionContext>) -> Self {
        let quota = Quota::per_minute(NonZeroU32::new(FAILED_AUTH_PER_MINUTE).expect("non-zero"));
        Self {
            permits: Arc::new(Semaphore::new(config.max_concurrent)),
            failures: RateLimiter::keyed(quota),
            config,
            profiles,
            contexts,
        }
    }

    /// What the startup log says, never including a secret.
    pub fn describe(&self) -> String {
        format!(
            "EXPERIMENTAL SQL endpoint enabled: {} profile(s), datasets {:?}, default {} / max {} rows, {}s timeout, {} MB memory pool, {} concurrent, parallelism {}",
            self.profiles.len(),
            { let mut d: Vec<_> = self.contexts.keys().cloned().collect(); d.sort(); d },
            self.config.default_rows,
            self.config.max_rows,
            self.config.timeout_secs,
            self.config.memory_mb,
            self.config.max_concurrent,
            self.config.parallelism,
        )
    }

    fn failed_login(&self, ip: IpAddr, id: &str, why: &str) -> Response {
        tracing::warn!(target: "sql_audit", ip = %ip, profile = id, outcome = why, "SQL authentication failed");
        if let Err(not_until) = self.failures.check_key(&ip) {
            let wait = not_until.wait_time_from(governor::clock::Clock::now(&governor::clock::DefaultClock::default()));
            return too_many_requests(MODULE, "Too many failed authentication attempts.", wait.as_secs().max(1));
        }
        unauthorized()
    }

    pub async fn handle(&self, peer: SocketAddr, headers: &HeaderMap, req: SqlRequest) -> Response {
        let ip = crate::rate_limit::client_ip(headers, peer);

        // 1. Who is this? No credential is a plain 401; a wrong one is counted.
        let Some(auth) = headers.get(header::AUTHORIZATION).and_then(|v| v.to_str().ok()) else {
            return unauthorized();
        };
        let Some((id, token)) = parse_basic(auth) else {
            return self.failed_login(ip, "-", "malformed");
        };
        let Some(profile) = self.profiles.authenticate(&id, &token) else {
            return self.failed_login(ip, &id, "bad_credentials");
        };

        // 2. May they use SQL, and on this dataset?
        let Some(granted) = &profile.sql_datasets else {
            return json_response(StatusCode::FORBIDDEN, "This profile is not granted SQL access.", Value::Null);
        };
        if !DATASETS.contains(&req.dataset.as_str()) {
            return json_response(
                StatusCode::BAD_REQUEST,
                &format!("Unknown dataset {:?}. Available: {}.", req.dataset, DATASETS.join(", ")),
                Value::Null,
            );
        }
        if !granted.contains(&req.dataset) {
            return json_response(StatusCode::FORBIDDEN, "This profile is not granted that dataset.", Value::Null);
        }
        let Some(ctx) = self.contexts.get(&req.dataset) else {
            return json_response(
                StatusCode::NOT_FOUND,
                &format!("Dataset {:?} is not loaded on this server.", req.dataset),
                Value::Null,
            );
        };
        if req.sql.trim().is_empty() {
            return json_response(StatusCode::BAD_REQUEST, "sql is empty.", Value::Null);
        }

        // 3. Room on this pod? Refuse rather than queue.
        let Ok(_permit) = self.permits.clone().try_acquire_owned() else {
            return too_many_requests(MODULE, "The server is running its maximum number of SQL queries; retry shortly.", 1);
        };

        let limit = req.limit.unwrap_or(self.config.default_rows).clamp(1, self.config.max_rows);
        let started = Instant::now();
        let outcome = execute(ctx, &req.sql, limit, Duration::from_secs(self.config.timeout_secs)).await;
        let ms = started.elapsed().as_millis() as u64;
        let sql_hash: String = Sha256::digest(req.sql.as_bytes()).iter().take(6).map(|b| format!("{b:02x}")).collect();
        let audit = |outcome: &str, rows: usize| {
            tracing::info!(target: "sql_audit", profile = %id, dataset = %req.dataset, sql_len = req.sql.len(), sql_hash = %sql_hash, rows, ms, outcome, "SQL request");
        };
        tracing::debug!(target: "sql_audit", profile = %id, sql = %req.sql, "SQL text");

        match outcome {
            Ok(out) => {
                audit("ok", out.rows.len());
                let mut limitations = vec![
                    json!({"code": "experimental", "message": "The SQL endpoint is experimental: it may change or be removed without notice, and the dialect is DataFusion's."}),
                    json!({"code": "read_only", "message": "Only read-only statements run; the embedding (vector) columns are not exposed."}),
                ];
                if out.truncated {
                    limitations.push(json!({"code": "truncated", "message": format!("The result was cut at {limit} rows.")}));
                }
                json_response(
                    StatusCode::OK,
                    "ok",
                    json!({
                        "dataset": req.dataset,
                        "columns": out.columns.iter().map(|(n, t)| json!({"name": n, "type": t})).collect::<Vec<_>>(),
                        "row_count": out.rows.len(),
                        "limit": limit,
                        "truncated": out.truncated,
                        "rows": out.rows,
                        "limitations": limitations,
                    }),
                )
            }
            Err(QueryError::Invalid(msg)) => {
                audit("invalid", 0);
                json_response(StatusCode::BAD_REQUEST, &msg, Value::Null)
            }
            Err(QueryError::Timeout) => {
                audit("timeout", 0);
                json_response(
                    StatusCode::GATEWAY_TIMEOUT,
                    &format!("The statement ran longer than {} seconds and was cancelled.", self.config.timeout_secs),
                    Value::Null,
                )
            }
            Err(QueryError::Resources(msg)) => {
                audit("resources", 0);
                json_response(StatusCode::UNPROCESSABLE_ENTITY, &format!("The query needed more memory than allowed ({} MB): {msg}", self.config.memory_mb), Value::Null)
            }
            Err(QueryError::Failed(msg)) => {
                audit("failed", 0);
                tracing::error!(target: "sql_audit", detail = %msg, "SQL execution failed");
                json_response(StatusCode::INTERNAL_SERVER_ERROR, "The query failed.", Value::Null)
            }
        }
    }
}

// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use datafusion::arrow::{
        array::{Float32Array, Int64Array, StringArray},
        datatypes::{DataType, Field, Schema},
        record_batch::RecordBatch,
    };
    use datafusion::datasource::MemTable;

    fn token_hash(token: &str) -> String {
        Sha256::digest(token.as_bytes()).iter().map(|b| format!("{b:02x}")).collect()
    }

    fn cfg() -> SqlConfig {
        SqlConfig::from_lookup(&|k| (k == "COMPANY_DNS_SQL_ENABLED").then(|| "true".to_string()))
            .unwrap()
            .unwrap()
    }

    /// 50 rows with an id, a name and a `vector_demo` column, as `things`.
    async fn demo_state(profiles_json: &str) -> SqlState {
        let schema = Arc::new(Schema::new(vec![
            Field::new("id", DataType::Int64, false),
            Field::new("name", DataType::Utf8, true),
            Field::new("vector_demo", DataType::Float32, false),
        ]));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(Int64Array::from((0..50).collect::<Vec<_>>())),
                Arc::new(StringArray::from((0..50).map(|i| if i == 3 { None } else { Some(format!("n{i}")) }).collect::<Vec<_>>())),
                Arc::new(Float32Array::from(vec![0.5; 50])),
            ],
        )
        .unwrap();
        let source = SessionContext::new();
        source.register_table("things", Arc::new(MemTable::try_new(schema, vec![vec![batch]]).unwrap())).unwrap();
        let config = cfg();
        let ctx = build_query_context(&source, &["things".to_string()], &config).await.unwrap();
        let mut contexts = HashMap::new();
        contexts.insert("sic".to_string(), ctx);
        SqlState::from_parts(config, Profiles::parse(profiles_json).unwrap(), contexts)
    }

    fn profiles_json(token: &str, datasets: &str) -> String {
        format!(
            r#"{{"profiles": {{"tester": {{"secret_sha256": "{}", "sql": {{"datasets": {datasets}}}}}, "nosql": {{"secret_sha256": "{}"}}}}}}"#,
            token_hash(token),
            token_hash("other-token")
        )
    }

    fn basic(id: &str, token: &str) -> HeaderMap {
        let mut h = HeaderMap::new();
        let v = base64::engine::general_purpose::STANDARD.encode(format!("{id}:{token}"));
        h.insert(header::AUTHORIZATION, HeaderValue::from_str(&format!("Basic {v}")).unwrap());
        h
    }

    fn peer() -> SocketAddr {
        "127.0.0.1:5000".parse().unwrap()
    }

    fn req(sql: &str) -> SqlRequest {
        SqlRequest { dataset: "sic".into(), sql: sql.into(), limit: None }
    }

    async fn call(state: &SqlState, headers: &HeaderMap, r: SqlRequest) -> (StatusCode, Value) {
        let resp = state.handle(peer(), headers, r).await;
        let status = resp.status();
        let bytes = axum::body::to_bytes(resp.into_body(), 10 * 1024 * 1024).await.unwrap();
        (status, serde_json::from_slice(&bytes).unwrap_or(Value::Null))
    }

    // --- config ---

    fn lookup(pairs: &'static [(&'static str, &'static str)]) -> impl Fn(&str) -> Option<String> {
        move |k| pairs.iter().find(|(n, _)| *n == k).map(|(_, v)| v.to_string())
    }

    #[test]
    fn off_by_default_and_defaults_when_on() {
        assert_eq!(SqlConfig::from_lookup(&lookup(&[])).unwrap(), None);
        assert_eq!(SqlConfig::from_lookup(&lookup(&[("COMPANY_DNS_SQL_ENABLED", "false")])).unwrap(), None);
        let c = cfg();
        assert_eq!((c.default_rows, c.max_rows, c.timeout_secs, c.memory_mb, c.max_concurrent, c.parallelism), (1000, 10000, 10, 256, 4, 2));
    }

    #[test]
    fn config_overrides_and_rejections() {
        let c = SqlConfig::from_lookup(&lookup(&[
            ("COMPANY_DNS_SQL_ENABLED", "1"),
            ("COMPANY_DNS_SQL_MAX_ROWS", "50"),
            ("COMPANY_DNS_SQL_DEFAULT_ROWS", "5"),
            ("COMPANY_DNS_SQL_TIMEOUT_SECS", "3"),
        ]))
        .unwrap()
        .unwrap();
        assert_eq!((c.default_rows, c.max_rows, c.timeout_secs), (5, 50, 3));
        for bad in [
            &[("COMPANY_DNS_SQL_ENABLED", "maybe")][..],
            &[("COMPANY_DNS_SQL_ENABLED", "true"), ("COMPANY_DNS_SQL_MAX_ROWS", "abc")][..],
            &[("COMPANY_DNS_SQL_ENABLED", "true"), ("COMPANY_DNS_SQL_TIMEOUT_SECS", "0")][..],
            &[("COMPANY_DNS_SQL_ENABLED", "true"), ("COMPANY_DNS_SQL_DEFAULT_ROWS", "20000")][..],
        ] {
            let pairs: &'static [(&'static str, &'static str)] = Box::leak(bad.to_vec().into_boxed_slice());
            assert!(SqlConfig::from_lookup(&lookup(pairs)).is_err(), "{bad:?}");
        }
    }

    // --- profiles and Basic Auth ---

    #[test]
    fn profiles_parse_and_reject() {
        assert!(Profiles::parse(&profiles_json("t", r#"["sic","edgar"]"#)).is_ok());
        assert!(Profiles::parse("{}").is_err());
        assert!(Profiles::parse(r#"{"profiles": {}}"#).is_err());
        assert!(Profiles::parse(r#"{"profiles": {"a": {"secret_sha256": "short"}}}"#).is_err());
        assert!(Profiles::parse(&profiles_json("t", r#"["nope"]"#)).is_err(), "unknown dataset");
        let typo = format!(r#"{{"profiles": {{"a": {{"secret_sha256": "{}", "limits": {{}}}}}}}}"#, token_hash("t"));
        assert!(Profiles::parse(&typo).is_err(), "unknown keys are errors, not silently ignored");
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
        let p = Profiles::parse(&profiles_json("good-token", r#"["sic"]"#)).unwrap();
        assert!(p.authenticate("tester", "good-token").is_some());
        assert!(p.authenticate("tester", "bad-token").is_none());
        assert!(p.authenticate("nobody", "good-token").is_none());
    }

    // --- the handler ---

    #[tokio::test]
    async fn no_credential_is_401_with_challenge() {
        let s = demo_state(&profiles_json("tok", r#"["sic"]"#)).await;
        let resp = s.handle(peer(), &HeaderMap::new(), req("select 1")).await;
        assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
        assert!(resp.headers().get(header::WWW_AUTHENTICATE).unwrap().to_str().unwrap().starts_with("Basic"));
    }

    #[tokio::test]
    async fn forged_origin_is_accepted_for_nothing() {
        let s = demo_state(&profiles_json("tok", r#"["sic"]"#)).await;
        let mut h = HeaderMap::new();
        h.insert(header::ORIGIN, HeaderValue::from_static("https://mediumroast.io"));
        h.insert(header::REFERER, HeaderValue::from_static("https://mediumroast.io/"));
        let (status, _) = call(&s, &h, req("select 1")).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn wrong_token_401_and_failures_are_throttled() {
        let s = demo_state(&profiles_json("tok", r#"["sic"]"#)).await;
        let bad = basic("tester", "wrong");
        for _ in 0..FAILED_AUTH_PER_MINUTE {
            assert_eq!(call(&s, &bad, req("select 1")).await.0, StatusCode::UNAUTHORIZED);
        }
        assert_eq!(call(&s, &bad, req("select 1")).await.0, StatusCode::TOO_MANY_REQUESTS);
        // a correct credential still works for the same source
        assert_eq!(call(&s, &basic("tester", "tok"), req("select 1")).await.0, StatusCode::OK);
    }

    #[tokio::test]
    async fn profile_without_sql_or_dataset_is_403() {
        let s = demo_state(&profiles_json("tok", r#"["edgar"]"#)).await;
        assert_eq!(call(&s, &basic("nosql", "other-token"), req("select 1")).await.0, StatusCode::FORBIDDEN);
        assert_eq!(call(&s, &basic("tester", "tok"), req("select 1")).await.0, StatusCode::FORBIDDEN, "sic not granted");
    }

    #[tokio::test]
    async fn unknown_dataset_and_empty_sql_are_400() {
        let s = demo_state(&profiles_json("tok", r#"["sic"]"#)).await;
        let h = basic("tester", "tok");
        let mut r = req("select 1");
        r.dataset = "nope".into();
        assert_eq!(call(&s, &h, r).await.0, StatusCode::BAD_REQUEST);
        assert_eq!(call(&s, &h, req("   ")).await.0, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn select_works_and_vectors_are_hidden() {
        let s = demo_state(&profiles_json("tok", r#"["sic"]"#)).await;
        let h = basic("tester", "tok");
        let (status, body) = call(&s, &h, req("select id, name from things where id < 5 order by id")).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["data"]["row_count"], 5);
        assert_eq!(body["data"]["rows"][3]["name"], Value::Null, "nulls are explicit");
        assert_eq!(body["data"]["columns"][0]["name"], "id");
        assert!(body["data"]["limitations"].as_array().unwrap().iter().any(|l| l["code"] == "experimental"));

        // SELECT * must not return the vector column, and naming it must fail.
        let (_, star) = call(&s, &h, req("select * from things limit 1")).await;
        assert!(star["data"]["rows"][0].get("vector_demo").is_none());
        assert_eq!(call(&s, &h, req("select vector_demo from things")).await.0, StatusCode::BAD_REQUEST);
        // information_schema agrees
        let (_, cols) = call(&s, &h, req("select column_name from information_schema.columns where table_name = 'things'")).await;
        let names: Vec<_> = cols["data"]["rows"].as_array().unwrap().iter().map(|r| r["column_name"].as_str().unwrap().to_string()).collect();
        assert!(names.contains(&"name".to_string()) && !names.iter().any(|n| n.starts_with("vector_")));
    }

    #[tokio::test]
    async fn empty_result_is_an_empty_list() {
        let s = demo_state(&profiles_json("tok", r#"["sic"]"#)).await;
        let (status, body) = call(&s, &basic("tester", "tok"), req("select id from things where id < 0")).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["data"]["rows"], json!([]));
        assert_eq!(body["data"]["row_count"], 0);
    }

    #[tokio::test]
    async fn row_cap_and_limit_clamp() {
        let s = demo_state(&profiles_json("tok", r#"["sic"]"#)).await;
        let h = basic("tester", "tok");
        let mut r = req("select id from things");
        r.limit = Some(10);
        let (_, body) = call(&s, &h, r).await;
        assert_eq!(body["data"]["row_count"], 10);
        assert_eq!(body["data"]["truncated"], true);
        // a limit above the ceiling is clamped to it (ceiling 10000, data is 50 rows)
        let mut r = req("select id from things");
        r.limit = Some(1_000_000);
        let (_, body) = call(&s, &h, r).await;
        assert_eq!(body["data"]["limit"], 10000);
        assert_eq!(body["data"]["truncated"], false);
    }

    #[tokio::test]
    async fn only_read_only_single_statements_run() {
        let s = demo_state(&profiles_json("tok", r#"["sic"]"#)).await;
        let h = basic("tester", "tok");
        for sql in [
            "insert into things values (1, 'x', 0.1)",
            "create table t2 as select * from things",
            "drop table things",
            "create external table e (a int) stored as csv location '/etc/passwd'",
            "copy things to '/tmp/out.csv'",
            "set datafusion.execution.batch_size = 1",
            "select 1; select 2",
            "select * from '/etc/passwd'",
            "select * from 'file:///etc/hosts'",
        ] {
            let (status, body) = call(&s, &h, req(sql)).await;
            assert_eq!(status, StatusCode::BAD_REQUEST, "{sql} -> {body}");
        }
        // the table is still there afterwards
        assert_eq!(call(&s, &h, req("select count(*) as n from things")).await.1["data"]["rows"][0]["n"], 50);
    }

    #[tokio::test]
    async fn timeout_cancels_the_statement() {
        let ctx = SessionContext::new();
        let out = execute(&ctx, "select count(*) from generate_series(1, 5000000000) t1 cross join generate_series(1, 5000000000) t2", 10, Duration::from_millis(300)).await;
        assert!(matches!(out, Err(QueryError::Timeout)), "{out:?}", out = out.as_ref().err());
    }

    #[tokio::test]
    async fn concurrency_cap_refuses_instead_of_queueing() {
        let s = demo_state(&profiles_json("tok", r#"["sic"]"#)).await;
        let held: Vec<_> = (0..s.config.max_concurrent).map(|_| s.permits.clone().try_acquire_owned().unwrap()).collect();
        let resp = s.handle(peer(), &basic("tester", "tok"), req("select 1")).await;
        assert_eq!(resp.status(), StatusCode::TOO_MANY_REQUESTS);
        assert!(resp.headers().get(header::RETRY_AFTER).is_some());
        drop(held);
        assert_eq!(call(&s, &basic("tester", "tok"), req("select 1")).await.0, StatusCode::OK);
    }
}
