pub mod embed;
pub mod lookup;
pub mod similarity;

use datafusion::datasource::file_format::options::ArrowReadOptions;
use datafusion::prelude::*;

pub use embed::{model_info, Embedders, TokenInfo};
pub use similarity::SearchHit;

/// US SIC data access - promoted from `experiments/df-spike/` (real-file
/// read validated, `go-duckdb-rewrite.md` §7.3/§7.4) and
/// `experiments/ic-similarity-service/` (vector search over it, §7.6-
/// §7.8). One `.feather` file backs both V3-parity lookups
/// (`lookup.rs`) and the new similarity endpoint (`similarity.rs`) -
/// same table, different queries.
pub struct SicCatalog {
    pub(crate) ctx: SessionContext,
}

impl SicCatalog {
    /// Loads the Mediumroast SIC `.feather` file (`tmp/us_flat.feather`
    /// for lookups, `tmp/us_flat_embedded.feather` once vectors are
    /// needed too - same schema, the embedded version just has extra
    /// vector columns) and registers it as table `sic_data`.
    pub async fn open(path: &str) -> anyhow::Result<Self> {
        let ctx = SessionContext::new();
        let opts = ArrowReadOptions {
            file_extension: ".feather",
            ..ArrowReadOptions::default()
        };
        let df = ctx.read_arrow(path, opts).await?;
        ctx.register_table("sic_data", df.into_view())?;
        Ok(Self { ctx })
    }
}
