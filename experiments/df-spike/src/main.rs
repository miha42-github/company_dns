use datafusion::datasource::file_format::options::ArrowReadOptions;
use datafusion::prelude::*;

// See ../README.md and docs/plans/go-duckdb-rewrite.md §7 for context.
// Run from this directory with:
//   cargo run --release -- /path/to/some.feather
// Defaults to tmp/us_flat.feather at the repo root if no path is given
// (not committed to the repo - see ../README.md).
#[tokio::main]
async fn main() -> datafusion::error::Result<()> {
    let ctx = SessionContext::new();

    let path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "../../tmp/us_flat.feather".to_string());

    println!("Reading {path} via read_arrow (Feather V2 == Arrow IPC file format)...");
    let opts = ArrowReadOptions {
        file_extension: ".feather",
        ..ArrowReadOptions::default()
    };
    let df = ctx.read_arrow(path.as_str(), opts).await?;

    println!("\n=== Schema ===");
    println!("{:#?}", df.schema());

    let count = df.clone().count().await?;
    println!("\n=== Row count === {count}");

    // Adjust these column names/filter if pointing at a different file -
    // the query below matches the US SIC schema this spike was written
    // against (section_id, section_desc, division_desc, ...).
    ctx.register_table("sic", df.into_view())?;

    let filtered = ctx
        .sql(
            "SELECT section_id, section_desc, count(*) as n \
             FROM sic \
             WHERE division_desc = 'Agricultural Production Crops' \
             GROUP BY section_id, section_desc",
        )
        .await?;
    filtered.show().await?;

    Ok(())
}
