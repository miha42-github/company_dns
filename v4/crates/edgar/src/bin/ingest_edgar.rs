//! Ingest binary for the EDGAR "10-x initial catalog"
//! (`docs/plans/v4-server-prototype.md` §4). Fetches one quarter's
//! filing index via `edgarkit`, filters to the `'10-%'` form family,
//! and writes it to `./tmp/edgar_10x_catalog.feather` at the repo
//! root - the same staging location the SIC `.feather` files already
//! use, covered by the same `.gitignore` entry.
//!
//! Usage:
//!   cargo run --release --bin ingest-edgar -- 2025 2
//!   cargo run --release --bin ingest-edgar -- 2025 2 /custom/output/path.feather
//!
//! Catalog freshness (`v4-server-prototype.md` §4, §10) is a build-time
//! concern in the real deployment - a scheduled GitHub Actions workflow
//! re-runs this binary and bakes the result into the image - not
//! something this binary or the server needs any logic for beyond
//! "run me and produce a file."

use company_dns_edgar::catalog::write_catalog_feather;
use edgarkit::{Edgar, EdgarPeriod, Quarter};
use std::path::PathBuf;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let year: i32 = args
        .next()
        .expect("usage: ingest-edgar <year> <quarter 1-4> [output-path]")
        .parse()?;
    let quarter_no: u8 = args
        .next()
        .expect("usage: ingest-edgar <year> <quarter 1-4> [output-path]")
        .parse()?;
    let quarter = match quarter_no {
        1 => Quarter::Q1,
        2 => Quarter::Q2,
        3 => Quarter::Q3,
        4 => Quarter::Q4,
        other => anyhow::bail!("quarter must be 1-4, got {other}"),
    };

    // Repo root's tmp/ - three levels up from v4/crates/edgar/, matching
    // where tmp/us_flat.feather and tmp/us_flat_embedded.feather already
    // live when this binary is run from its own crate directory (cargo's
    // default). If invoked from elsewhere, pass an explicit output path.
    let default_out = PathBuf::from("../../../tmp/edgar_10x_catalog.feather");
    let out_path = args.next().map(PathBuf::from).unwrap_or(default_out);

    let edgar = Edgar::new(company_dns_edgar::USER_AGENT)?;
    let period = EdgarPeriod::new(year, quarter)?;

    println!("Fetching {year} Q{quarter_no} filing index via edgarkit...");
    let rows = write_catalog_feather(&edgar, period, &out_path).await?;
    println!(
        "Wrote {rows} rows ('10-%' filings) to {}",
        out_path.display()
    );

    Ok(())
}
