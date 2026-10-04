//! Ingest binary for the EDGAR "10-x catalog"
//! (`docs/plans/v4-server-prototype.md` §4, `docs/plans/v4-deployment.md`
//! §3.2). Fetches quarterly SEC filing indexes via `edgarkit`, keeps the
//! `'10-%'` form family (10-K, 10-Q, 10-D, ...), merges the quarters into one
//! catalog and writes it to a `.feather` file the server reads.
//!
//! Usage (see `periods::USAGE`):
//!   ingest-edgar                      last 2 years: the 8 most recent completed quarters
//!   ingest-edgar --years 1            last 1 year (4 quarters)
//!   ingest-edgar --from 2024Q1 --to 2025Q4
//!   ingest-edgar 2025 2               one quarter (the original form)
//!   ingest-edgar --out /path/to/catalog.feather
//!
//! Output defaults to `edgar_10x_catalog.feather` inside the data directory
//! (`COMPANY_DNS_DATA_DIR`, see `data_dir.rs`; the repo-root `tmp/` when
//! unset). The catalog is a rolling window, rebuilt from scratch each time:
//! the quarterly build re-runs this with no arguments, so what ships is always
//! the last two years of completed quarters. Any quarter that fails to
//! download aborts the whole run and leaves the existing catalog untouched
//! (the file is written to a temporary name and renamed into place).

use chrono::Utc;
use company_dns_edgar::catalog::{fetch_quarter_rows, write_catalog_rows};
use company_dns_edgar::data_dir::{data_dir, EDGAR_CATALOG_FILE};
use company_dns_edgar::periods::{parse_args, USAGE};
use edgarkit::{Edgar, EdgarPeriod, Quarter};
use std::collections::HashMap;

fn edgar_quarter(q: u8) -> Quarter {
    match q {
        1 => Quarter::Q1,
        2 => Quarter::Q2,
        3 => Quarter::Q3,
        _ => Quarter::Q4,
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "-h" || a == "--help") {
        println!("{USAGE}");
        return Ok(());
    }
    let today = Utc::now().date_naive();
    let plan = parse_args(&args, today)?;
    let out_path = plan.out.clone().unwrap_or_else(|| data_dir().join(EDGAR_CATALOG_FILE));

    let first = plan.quarters.first().expect("a plan always has a quarter");
    let last = plan.quarters.last().expect("a plan always has a quarter");
    println!(
        "Ingesting {} quarter{} ({first} to {last}) into {}",
        plan.quarters.len(),
        if plan.quarters.len() == 1 { "" } else { "s" },
        out_path.display()
    );

    let edgar = Edgar::new(company_dns_edgar::USER_AGENT)?;
    let mut rows = Vec::new();
    for quarter in &plan.quarters {
        let period = EdgarPeriod::new(quarter.year, edgar_quarter(quarter.q))?;
        let fetched = fetch_quarter_rows(&edgar, period)
            .await
            .map_err(|e| anyhow::anyhow!("{quarter}: {e} - nothing was written"))?;
        println!("  {quarter}: {} 10-x filings", fetched.len());
        rows.extend(fetched);
    }

    let metadata: HashMap<String, String> = HashMap::from([
        ("source".into(), "SEC EDGAR quarterly form index via edgarkit; form types starting 10-".into()),
        ("generated_at".into(), Utc::now().to_rfc3339()),
        ("first_quarter".into(), first.to_string()),
        ("last_quarter".into(), last.to_string()),
        ("quarters".into(), plan.quarters.len().to_string()),
        ("ingest_version".into(), "ingest-edgar-2".into()),
    ]);
    let written = write_catalog_rows(&rows, &out_path, metadata)?;
    println!("Wrote {written} rows ({} before de-duplication) to {}", rows.len(), out_path.display());
    Ok(())
}
