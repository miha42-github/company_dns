// Second half of the ../edgar-spike test: loads the .feather file
// ../edgar-spike wrote (real SEC EDGAR quarterly index data, filtered
// to '10-%' forms) with DataFusion and runs real SQL against it - same
// read_arrow pattern ../df-spike validated against a real Mediumroast
// file (docs/plans/go-duckdb-rewrite.md sec7). Split into its own crate
// because edgarkit and DataFusion 42 can't share one Cargo.toml - see
// ../edgar-spike/Cargo.toml for the real chrono/arrow-arith conflict
// that forces this. Run ../edgar-spike first to produce the file.

use datafusion::datasource::file_format::options::ArrowReadOptions;
use datafusion::prelude::*;

#[tokio::main]
async fn main() -> datafusion::error::Result<()> {
    let path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "../../tmp/edgar_10series_2025q2.feather".to_string());

    println!("Reading {path} via read_arrow (Feather V2 == Arrow IPC file format)...");
    let ctx = SessionContext::new();
    let opts = ArrowReadOptions {
        file_extension: ".feather",
        ..ArrowReadOptions::default()
    };
    let df = ctx.read_arrow(path.as_str(), opts).await?;

    println!("\n=== Schema ===");
    println!("{:#?}", df.schema());

    let count = df.clone().count().await?;
    println!("\n=== Row count === {count}");

    ctx.register_table("edgar_index", df.into_view())?;

    // A query representative of what the real fallback-cache lookup
    // would do: find one company's cached 10-%% filings by CIK (IBM,
    // same CIK used throughout ../edgar-spike's tests).
    println!("\n=== IBM (cik=51143) 10-%% filings in this quarter's index ===");
    let ibm = ctx
        .sql(
            "SELECT company_name, form_type, year, month, day, accession \
             FROM edgar_index WHERE cik = 51143 \
             ORDER BY year DESC, month DESC, day DESC",
        )
        .await?;
    ibm.show().await?;

    println!("=== Filing counts by form type ===");
    let by_form = ctx
        .sql("SELECT form_type, count(*) as n FROM edgar_index GROUP BY form_type ORDER BY n DESC")
        .await?;
    by_form.show().await?;

    Ok(())
}
