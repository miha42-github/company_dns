//! Benchmark of the lookup queries against DataFusion's target partition count (docs/plans/v4-release-to-staging.md, finding 2).
//!
//!   cargo run --release -p company-dns-server --example partitions_bench -- <default|N> [data_dir]    (MEM=1 loads the tables into memory first)
//!
//! One configuration per process, so memory readings are not polluted by an earlier run. Prints one line:
//! partitions, cpus, per-query median and p95 (ms) for a US SIC lookup and an EDGAR name search, the wall time of 16 concurrent tasks x 25
//! queries, and the resident memory afterwards (MiB).
use datafusion::datasource::file_format::options::ArrowReadOptions;
use datafusion::prelude::{SessionConfig, SessionContext};
use std::time::Instant;

async fn run(ctx: &SessionContext, sql: &str) -> usize {
    ctx.sql(sql).await.unwrap().collect().await.unwrap().iter().map(|b| b.num_rows()).sum()
}

fn pct(v: &mut [f64], q: f64) -> f64 {
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    v[((v.len() - 1) as f64 * q).round() as usize]
}

fn rss_mib() -> f64 {
    let out = std::process::Command::new("ps").args(["-o", "rss=", "-p", &std::process::id().to_string()]).output().unwrap();
    String::from_utf8_lossy(&out.stdout).trim().parse::<f64>().unwrap_or(0.0) / 1024.0
}

#[tokio::main]
async fn main() {
    let mut args = std::env::args().skip(1);
    let setting = args.next().unwrap_or_else(|| "default".into());
    let dir = args.next().or_else(|| std::env::var("COMPANY_DNS_DATA_DIR").ok()).expect("pass the data directory as the second argument or set COMPANY_DNS_DATA_DIR");
    let cfg = if setting == "default" { SessionConfig::new() } else { SessionConfig::new().with_target_partitions(setting.parse().unwrap()) };
    let ctx = SessionContext::new_with_config(cfg);
    let opts = || ArrowReadOptions { file_extension: ".feather", ..ArrowReadOptions::default() };
    // MEM=1 loads each table into memory once (a MemTable) instead of reading the feather file on every query.
    let in_memory = std::env::var("MEM").is_ok();
    for (name, file) in [("sic_data", "us_flat_embedded.feather"), ("edgar_catalog", "edgar_10x_catalog.feather")] {
        let df = ctx.read_arrow(format!("{dir}/{file}"), opts()).await.unwrap();
        if in_memory {
            let schema = std::sync::Arc::new(df.schema().as_arrow().clone());
            let batches = df.collect().await.unwrap();
            let t = datafusion::datasource::MemTable::try_new(schema, vec![batches]).unwrap();
            ctx.register_table(name, std::sync::Arc::new(t)).unwrap();
        } else {
            ctx.register_table(name, df.into_view()).unwrap();
        }
    }
    let partitions = ctx.state().config().target_partitions();

    let sic = "SELECT DISTINCT section_id, section_desc, division_id, division_desc, group_id, group_desc, class_id, class_desc FROM sic_data WHERE class_id ILIKE '%357%' ORDER BY class_id";
    let edgar = "SELECT cik, company_name, form_type, year, month, day, accession FROM edgar_catalog WHERE company_name ILIKE '%apple%' ORDER BY year DESC, month DESC, day DESC";
    for _ in 0..20 {
        run(&ctx, sic).await;
        run(&ctx, edgar).await;
    }
    let mut times = (Vec::new(), Vec::new());
    for _ in 0..300 {
        let t = Instant::now();
        run(&ctx, sic).await;
        times.0.push(t.elapsed().as_secs_f64() * 1000.0);
        let t = Instant::now();
        run(&ctx, edgar).await;
        times.1.push(t.elapsed().as_secs_f64() * 1000.0);
    }
    let t = Instant::now();
    let mut tasks = Vec::new();
    for _ in 0..16 {
        let c = ctx.clone();
        tasks.push(tokio::spawn(async move {
            for _ in 0..25 {
                run(&c, sic).await;
                run(&c, edgar).await;
            }
        }));
    }
    for h in tasks {
        h.await.unwrap();
    }
    let wall = t.elapsed().as_secs_f64() * 1000.0;
    println!(
        "{} partitions={partitions:>2} cpus={} sic p50={:.2} p95={:.2} | edgar p50={:.2} p95={:.2} | 16x25 concurrent wall={wall:.0} ms ({:.0} q/s) | rss={:.0} MiB",
        if in_memory { "mem " } else { "file" }, std::thread::available_parallelism().map(|n| n.get()).unwrap_or(0),
        pct(&mut times.0, 0.5), pct(&mut times.0, 0.95), pct(&mut times.1, 0.5), pct(&mut times.1, 0.95),
        800.0 / (wall / 1000.0), rss_mib()
    );
}
