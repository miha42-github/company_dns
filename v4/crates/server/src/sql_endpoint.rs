//! EXPERIMENTAL SQL endpoint - `docs/plans/v4-sql-endpoint.md`.
//!
//! `POST /V4.0/sql` runs one read-only SQL statement against one dataset
//! (`sic` or `edgar`). It can use real CPU and memory, so it is closed by
//! default: off unless `COMPANY_DNS_SQL_ENABLED` is set, and every request needs
//! HTTP Basic Auth against the credentials file (`COMPANY_DNS_CREDENTIALS_FILE`, see `access.rs`), which
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
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
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
use governor::{DefaultDirectRateLimiter, Quota, RateLimiter};
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    net::SocketAddr,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::Semaphore;

use crate::access::{unauthorized, Access, Identity, SqlLimits};
use crate::envelope::{envelope, too_many_requests};

pub const MODULE: &str = "SqlEndpoint->query";
/// The only datasets there are. A profile naming anything else is a config error.
pub const DATASETS: [&str; 2] = ["sic", "edgar"];

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
    access: Arc<Access>,
    contexts: HashMap<String, SessionContext>,
    permits: Arc<Semaphore>,
    /// Per-profile caps, for the profiles whose `sql.limits` set any. The others use the
    /// server-wide values as they are.
    profile_limits: HashMap<String, ProfileLimits>,
}

/// A profile's effective SQL limits: its own values, each clamped by the server-wide ones.
struct ProfileLimits {
    max_rows: usize,
    timeout: Duration,
    /// Its own concurrency gate, on top of the server-wide one.
    permits: Arc<Semaphore>,
    /// Its own request rate (fleet-wide number divided across replicas).
    rate: Option<DefaultDirectRateLimiter>,
}

fn build_profile_limits(config: &SqlConfig, access: &Access) -> HashMap<String, ProfileLimits> {
    let mut out = HashMap::new();
    for (id, grant) in access.profiles().sql_grants() {
        let l = grant.limits;
        if l == SqlLimits::default() {
            continue;
        }
        let rate = l.requests_per_minute.map(|rpm| {
            let per_pod = crate::rate_limit::per_pod;
            let quota = Quota::per_minute(per_pod(rpm)).allow_burst(per_pod(l.burst.unwrap_or(rpm)));
            RateLimiter::direct(quota)
        });
        out.insert(
            id.to_string(),
            ProfileLimits {
                max_rows: l.max_rows.unwrap_or(config.max_rows).min(config.max_rows),
                timeout: Duration::from_secs(l.timeout_secs.unwrap_or(config.timeout_secs).min(config.timeout_secs)),
                permits: Arc::new(Semaphore::new(l.concurrency.unwrap_or(config.max_concurrent).min(config.max_concurrent))),
                rate,
            },
        );
    }
    out
}

fn json_response(status: StatusCode, message: &str, data: Value) -> Response {
    (status, Json(envelope(status.as_u16(), message, MODULE, data))).into_response()
}

impl SqlState {
    pub async fn build(
        config: SqlConfig,
        access: Arc<Access>,
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
        Ok(Self::from_parts(config, access, contexts))
    }

    fn from_parts(config: SqlConfig, access: Arc<Access>, contexts: HashMap<String, SessionContext>) -> Self {
        let profile_limits = build_profile_limits(&config, &access);
        Self { permits: Arc::new(Semaphore::new(config.max_concurrent)), config, access, contexts, profile_limits }
    }

    /// What the startup log says, never including a secret.
    pub fn describe(&self) -> String {
        format!(
            "EXPERIMENTAL SQL endpoint enabled: {} profile(s), datasets {:?}, default {} / max {} rows, {}s timeout, {} MB memory pool, {} concurrent, parallelism {}",
            self.access.profiles().len(),
            { let mut d: Vec<_> = self.contexts.keys().cloned().collect(); d.sort(); d },
            self.config.default_rows,
            self.config.max_rows,
            self.config.timeout_secs,
            self.config.memory_mb,
            self.config.max_concurrent,
            self.config.parallelism,
        )
    }

    pub async fn handle(&self, peer: SocketAddr, headers: &HeaderMap, req: SqlRequest) -> Response {
        let ip = crate::rate_limit::client_ip(headers, peer);

        // 1. Who is this? No credential is a plain 401; a wrong one is counted.
        let (id, profile) = match self.access.identify(headers, ip) {
            Identity::Anonymous => return unauthorized(),
            Identity::Rejected(response) => return response,
            Identity::Profile { id, profile } => (id, profile),
        };

        // 2. May they use SQL, and on this dataset?
        let Some(sql_grant) = &profile.sql else {
            return json_response(StatusCode::FORBIDDEN, "This profile is not granted SQL access.", Value::Null);
        };
        if !DATASETS.contains(&req.dataset.as_str()) {
            return json_response(
                StatusCode::BAD_REQUEST,
                &format!("Unknown dataset {:?}. Available: {}.", req.dataset, DATASETS.join(", ")),
                Value::Null,
            );
        }
        if !sql_grant.datasets.contains(&req.dataset) {
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

        // 3. This profile's own limits, then room on this pod. Refuse rather than queue.
        let pl = self.profile_limits.get(&id);
        if let Some(rate) = pl.and_then(|p| p.rate.as_ref()) {
            if let Err(not_until) = rate.check() {
                let wait = not_until.wait_time_from(governor::clock::Clock::now(&governor::clock::DefaultClock::default()));
                return too_many_requests(MODULE, "This profile's SQL request limit was exceeded.", wait.as_secs().max(1));
            }
        }
        let _profile_permit = match pl {
            Some(p) => match p.permits.clone().try_acquire_owned() {
                Ok(permit) => Some(permit),
                Err(_) => return too_many_requests(MODULE, "This profile is running its maximum number of SQL queries; retry shortly.", 1),
            },
            None => None,
        };
        let Ok(_permit) = self.permits.clone().try_acquire_owned() else {
            return too_many_requests(MODULE, "The server is running its maximum number of SQL queries; retry shortly.", 1);
        };

        let max_rows = pl.map_or(self.config.max_rows, |p| p.max_rows);
        let timeout = pl.map_or(Duration::from_secs(self.config.timeout_secs), |p| p.timeout);
        let limit = req.limit.unwrap_or(self.config.default_rows.min(max_rows)).clamp(1, max_rows);
        let started = Instant::now();
        let outcome = execute(ctx, &req.sql, limit, timeout).await;
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
                    &format!("The statement ran longer than {} seconds and was cancelled.", timeout.as_secs()),
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

    use crate::access::{tests::test_profiles, FAILED_AUTH_PER_MINUTE, Profiles};
    use axum::http::{header, HeaderValue};
    use base64::Engine;

    fn cfg() -> SqlConfig {
        SqlConfig::from_lookup(&|k| (k == "COMPANY_DNS_SQL_ENABLED").then(|| "true".to_string()))
            .unwrap()
            .unwrap()
    }

    /// 50 rows with an id, a name and a `vector_demo` column, as `things`.
    async fn demo_state(profiles: Profiles) -> SqlState {
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
        SqlState::from_parts(config, Arc::new(Access::new(profiles)), contexts)
    }

    /// Profiles `tester` (token `token`, SQL on `datasets`) and `nosql` (no SQL grant).
    fn profiles_json(token: &str, datasets: &str) -> Profiles {
        test_profiles(
            &[("tester", token), ("nosql", "other-token")],
            Some(&format!(r#"{{"profiles": {{"tester": {{"sql": {{"datasets": {datasets}}}}}}}}}"#)),
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

    // --- the handler ---

    #[tokio::test]
    async fn no_credential_is_401_with_challenge() {
        let s = demo_state(profiles_json("tok", r#"["sic"]"#)).await;
        let resp = s.handle(peer(), &HeaderMap::new(), req("select 1")).await;
        assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
        assert!(resp.headers().get(header::WWW_AUTHENTICATE).unwrap().to_str().unwrap().starts_with("Basic"));
    }

    #[tokio::test]
    async fn forged_origin_is_accepted_for_nothing() {
        let s = demo_state(profiles_json("tok", r#"["sic"]"#)).await;
        let mut h = HeaderMap::new();
        h.insert(header::ORIGIN, HeaderValue::from_static("https://mediumroast.io"));
        h.insert(header::REFERER, HeaderValue::from_static("https://mediumroast.io/"));
        let (status, _) = call(&s, &h, req("select 1")).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn wrong_token_401_and_failures_are_throttled() {
        let s = demo_state(profiles_json("tok", r#"["sic"]"#)).await;
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
        let s = demo_state(profiles_json("tok", r#"["edgar"]"#)).await;
        assert_eq!(call(&s, &basic("nosql", "other-token"), req("select 1")).await.0, StatusCode::FORBIDDEN);
        assert_eq!(call(&s, &basic("tester", "tok"), req("select 1")).await.0, StatusCode::FORBIDDEN, "sic not granted");
    }

    #[tokio::test]
    async fn unknown_dataset_and_empty_sql_are_400() {
        let s = demo_state(profiles_json("tok", r#"["sic"]"#)).await;
        let h = basic("tester", "tok");
        let mut r = req("select 1");
        r.dataset = "nope".into();
        assert_eq!(call(&s, &h, r).await.0, StatusCode::BAD_REQUEST);
        assert_eq!(call(&s, &h, req("   ")).await.0, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn select_works_and_vectors_are_hidden() {
        let s = demo_state(profiles_json("tok", r#"["sic"]"#)).await;
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
        let s = demo_state(profiles_json("tok", r#"["sic"]"#)).await;
        let (status, body) = call(&s, &basic("tester", "tok"), req("select id from things where id < 0")).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["data"]["rows"], json!([]));
        assert_eq!(body["data"]["row_count"], 0);
    }

    #[tokio::test]
    async fn row_cap_and_limit_clamp() {
        let s = demo_state(profiles_json("tok", r#"["sic"]"#)).await;
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
        let s = demo_state(profiles_json("tok", r#"["sic"]"#)).await;
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

    /// One profile, `lim` (token `tok`), with SQL on `sic` and these limits.
    fn limited_profiles(limits: &str) -> Profiles {
        test_profiles(
            &[("lim", "tok")],
            Some(&format!(r#"{{"profiles": {{"lim": {{"sql": {{"datasets": ["sic"], "limits": {limits}}}}}}}}}"#)),
        )
    }

    #[tokio::test]
    async fn a_profile_can_lower_rows_and_is_clamped_by_the_server_wide_ceiling() {
        let h = basic("lim", "tok");
        let s = demo_state(limited_profiles(r#"{"max_rows": 7}"#)).await;
        let (_, body) = call(&s, &h, req("select id from things")).await;
        assert_eq!(body["data"]["row_count"], 7, "default is cut to the profile's max");
        let mut r = req("select id from things");
        r.limit = Some(1000);
        assert_eq!(call(&s, &h, r).await.1["data"]["limit"], 7, "a request cannot raise it");

        // above the server-wide ceiling (10000): clamped down to it, never exceeded
        let s = demo_state(limited_profiles(r#"{"max_rows": 99999999}"#)).await;
        let mut r = req("select id from things");
        r.limit = Some(99_999_999);
        assert_eq!(call(&s, &h, r).await.1["data"]["limit"], 10000);
    }

    #[tokio::test]
    async fn a_profile_request_rate_limit_gives_429_with_retry_after() {
        // 20/min fleet-wide = 5 per pod
        let s = demo_state(limited_profiles(r#"{"requests_per_minute": 20}"#)).await;
        let h = basic("lim", "tok");
        for i in 0..5 {
            assert_eq!(call(&s, &h, req("select 1")).await.0, StatusCode::OK, "request {i}");
        }
        let resp = s.handle(peer(), &h, req("select 1")).await;
        assert_eq!(resp.status(), StatusCode::TOO_MANY_REQUESTS);
        assert!(resp.headers().get(header::RETRY_AFTER).is_some());
    }

    #[tokio::test]
    async fn a_profile_concurrency_limit_is_its_own_gate() {
        let s = demo_state(limited_profiles(r#"{"concurrency": 1}"#)).await;
        let h = basic("lim", "tok");
        let held = s.profile_limits["lim"].permits.clone().try_acquire_owned().unwrap();
        assert_eq!(call(&s, &h, req("select 1")).await.0, StatusCode::TOO_MANY_REQUESTS);
        assert!(s.permits.available_permits() > 0, "the server-wide gate was not the one that refused");
        drop(held);
        assert_eq!(call(&s, &h, req("select 1")).await.0, StatusCode::OK);
    }

    #[test]
    fn profile_limits_never_exceed_the_server_wide_ones() {
        let c = cfg(); // 10000 rows, 10 s, 4 concurrent
        let p = limited_profiles(r#"{"max_rows": 99999, "timeout_secs": 999, "concurrency": 99}"#);
        let l = &build_profile_limits(&c, &Access::new(p))["lim"];
        assert_eq!((l.max_rows, l.timeout, l.permits.available_permits()), (10000, Duration::from_secs(10), 4));
        let p = limited_profiles(r#"{"max_rows": 5, "timeout_secs": 2, "concurrency": 1}"#);
        let l = &build_profile_limits(&c, &Access::new(p))["lim"];
        assert_eq!((l.max_rows, l.timeout, l.permits.available_permits()), (5, Duration::from_secs(2), 1));
    }

    #[tokio::test]
    async fn concurrency_cap_refuses_instead_of_queueing() {
        let s = demo_state(profiles_json("tok", r#"["sic"]"#)).await;
        let held: Vec<_> = (0..s.config.max_concurrent).map(|_| s.permits.clone().try_acquire_owned().unwrap()).collect();
        let resp = s.handle(peer(), &basic("tester", "tok"), req("select 1")).await;
        assert_eq!(resp.status(), StatusCode::TOO_MANY_REQUESTS);
        assert!(resp.headers().get(header::RETRY_AFTER).is_some());
        drop(held);
        assert_eq!(call(&s, &basic("tester", "tok"), req("select 1")).await.0, StatusCode::OK);
    }
}
