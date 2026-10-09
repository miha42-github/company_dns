pub mod company_match;
pub mod map;
pub mod embed;
pub mod global;
pub mod hybrid;
pub mod lookup;
pub mod similarity;
pub mod systems;

use datafusion::datasource::file_format::options::ArrowReadOptions;
use datafusion::prelude::*;

pub use embed::{model_info, Embedders, TokenInfo};
pub use global::{GlobalSearchHit, GlobalSicMatch};
pub use hybrid::HybridHit;
pub use similarity::SearchHit;

/// One classification system registered into `SicCatalog`'s shared
/// `SessionContext` - the primary US table (`sic_data`, loaded by
/// `open()`) plus any additional systems (`register_system()`, e.g.
/// Japan SIC) as their data lands (`docs/plans/sic-global-search.md`).
/// `global.rs`'s fan-out query is built dynamically from this list, so
/// it never references a table that wasn't actually registered.
#[derive(Clone)]
pub(crate) struct SicSystem {
    pub table_name: String,
    /// Matches the `source_type` label the existing UI already expects
    /// per system (`static/index.html`'s per-source `x-if` templates,
    /// e.g. `result.source_type === 'Japan SIC'`) - not an arbitrary
    /// label invented here.
    pub source_label: String,
}

/// US SIC data access - promoted from `experiments/df-spike/` (real-file
/// read validated, `go-duckdb-rewrite.md` §7.3/§7.4) and
/// `experiments/ic-similarity-service/` (vector search over it, §7.6-
/// §7.8). One `.feather` file backs both V3-parity lookups
/// (`lookup.rs`) and the new similarity endpoint (`similarity.rs`) -
/// same table, different queries. Additional classification systems
/// (`register_system`) live alongside it in the same `SessionContext`,
/// each its own table, fanned out across by `global.rs`.
pub struct SicCatalog {
    pub(crate) ctx: SessionContext,
    pub(crate) systems: Vec<SicSystem>,
}

impl SicCatalog {
    /// Loads the Mediumroast SIC `.feather` file (`tmp/us_flat.feather`
    /// for lookups, `tmp/us_flat_embedded.feather` once vectors are
    /// needed too - same schema, the embedded version just has extra
    /// vector columns) and registers it as table `sic_data`, tagged
    /// `source_label: "US SIC"` for the global fan-out query.
    pub async fn open(path: &str) -> anyhow::Result<Self> {
        let ctx = SessionContext::new();
        let opts = ArrowReadOptions {
            file_extension: ".feather",
            ..ArrowReadOptions::default()
        };
        let df = ctx.read_arrow(path, opts).await?;
        ctx.register_table("sic_data", df.into_view())?;
        Ok(Self {
            ctx,
            systems: vec![SicSystem {
                table_name: "sic_data".to_string(),
                source_label: "US SIC".to_string(),
            }],
        })
    }

    /// What the experimental SQL endpoint (`docs/plans/v4-sql-endpoint.md`) is
    /// built from: this catalog's session and the names of every registered
    /// system table (US SIC plus whichever others loaded).
    pub fn query_source(&self) -> (SessionContext, Vec<String>) {
        (self.ctx.clone(), self.systems.iter().map(|s| s.table_name.clone()).collect())
    }

    /// Registers an additional classification system's `.feather` file
    /// (e.g. Japan SIC) as its own table in the same `SessionContext`,
    /// alongside the primary US table. Called before the catalog is
    /// wrapped in `Arc` (server startup, `main.rs`) - optional, callers
    /// should warn-and-continue rather than fail startup if a system's
    /// data file isn't available yet (same pattern as `EdgarCatalog`'s
    /// optional load).
    pub async fn register_system(
        &mut self,
        path: &str,
        table_name: &str,
        source_label: &str,
    ) -> anyhow::Result<()> {
        let opts = ArrowReadOptions {
            file_extension: ".feather",
            ..ArrowReadOptions::default()
        };
        let df = self.ctx.read_arrow(path, opts).await?;
        self.ctx.register_table(table_name, df.into_view())?;
        self.systems.push(SicSystem {
            table_name: table_name.to_string(),
            source_label: source_label.to_string(),
        });
        Ok(())
    }
}
