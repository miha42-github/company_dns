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

/// The most partitions a lookup query is split into by default. DataFusion's own default is the host's CPU count, which on a small table
/// costs more in coordination than it saves (docs/plans/v4-release-to-staging.md, finding 2: lookups got slower with more CPUs); 4 was the
/// best of 1, 2, 4, 8 and 16 in a benchmark of the real lookup queries against the real data.
pub const MAX_DEFAULT_QUERY_PARTITIONS: usize = 4;

/// The default query parallelism: the host's CPUs, but never more than [`MAX_DEFAULT_QUERY_PARTITIONS`].
pub fn default_query_parallelism() -> usize {
    std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1).min(MAX_DEFAULT_QUERY_PARTITIONS)
}

/// Reads a `.feather` file once and registers it as an in-memory table, so a query scans memory and does not re-read and re-decode the file
/// (the benchmark behind finding 2: resident memory fell from 217-241 MiB to 58-102 MiB and throughput roughly doubled or better).
async fn register_in_memory(ctx: &SessionContext, table: &str, path: &str) -> anyhow::Result<()> {
    let opts = ArrowReadOptions {
        file_extension: ".feather",
        ..ArrowReadOptions::default()
    };
    let df = ctx.read_arrow(path, opts).await?;
    let schema = std::sync::Arc::new(df.schema().as_arrow().clone());
    let batches = df.collect().await?;
    ctx.register_table(table, std::sync::Arc::new(datafusion::datasource::MemTable::try_new(schema, vec![batches])?))?;
    Ok(())
}

impl SicCatalog {
    /// Loads the Mediumroast SIC `.feather` file (`tmp/us_flat.feather`
    /// for lookups, `tmp/us_flat_embedded.feather` once vectors are
    /// needed too - same schema, the embedded version just has extra
    /// vector columns) and registers it as table `sic_data`, tagged
    /// `source_label: "US SIC"` for the global fan-out query.
    pub async fn open(path: &str) -> anyhow::Result<Self> {
        Self::open_with_parallelism(path, default_query_parallelism()).await
    }

    /// [`open`](Self::open) with an explicit number of partitions per query (the server's `COMPANY_DNS_QUERY_PARALLELISM`).
    pub async fn open_with_parallelism(path: &str, partitions: usize) -> anyhow::Result<Self> {
        let ctx = SessionContext::new_with_config(SessionConfig::new().with_target_partitions(partitions.max(1)));
        register_in_memory(&ctx, "sic_data", path).await?;
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
        register_in_memory(&self.ctx, table_name, path).await?;
        self.systems.push(SicSystem {
            table_name: table_name.to_string(),
            source_label: source_label.to_string(),
        });
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use datafusion::arrow::array::{ArrayRef, Int32Array, StringArray};
    use datafusion::arrow::datatypes::{DataType, Field, Schema};
    use datafusion::arrow::ipc::writer::FileWriter;
    use datafusion::arrow::record_batch::RecordBatch;

    fn write_feather(path: &std::path::Path) {
        let schema = std::sync::Arc::new(Schema::new(vec![Field::new("class_id", DataType::Utf8, false), Field::new("n", DataType::Int32, false)]));
        let cols: Vec<ArrayRef> = vec![std::sync::Arc::new(StringArray::from(vec!["3571", "3572"])), std::sync::Arc::new(Int32Array::from(vec![1, 2]))];
        let batch = RecordBatch::try_new(schema.clone(), cols).unwrap();
        let mut w = FileWriter::try_new(std::fs::File::create(path).unwrap(), &schema).unwrap();
        w.write(&batch).unwrap();
        w.finish().unwrap();
    }

    #[tokio::test]
    async fn an_opened_catalog_is_in_memory_with_the_requested_partitions() {
        let dir = std::env::temp_dir().join(format!("sic-mem-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let (us, extra) = (dir.join("us.feather"), dir.join("extra.feather"));
        write_feather(&us);
        write_feather(&extra);

        let mut cat = SicCatalog::open_with_parallelism(us.to_str().unwrap(), 3).await.unwrap();
        cat.register_system(extra.to_str().unwrap(), "sic_data_extra", "Extra").await.unwrap();
        assert_eq!(cat.ctx.state().config().target_partitions(), 3, "the requested partition count, not one per CPU");
        // Read once into memory: with both files deleted, queries on both tables still work (a file-backed table would fail here).
        std::fs::remove_file(&us).unwrap();
        std::fs::remove_file(&extra).unwrap();
        for table in ["sic_data", "sic_data_extra"] {
            let rows = cat.ctx.sql(&format!("SELECT class_id FROM {table} WHERE class_id ILIKE '%357%'")).await.unwrap().collect().await.unwrap();
            assert_eq!(rows.iter().map(|b| b.num_rows()).sum::<usize>(), 2, "{table} is served from memory, with the file gone");
        }
        assert!(default_query_parallelism() >= 1 && default_query_parallelism() <= MAX_DEFAULT_QUERY_PARTITIONS);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
