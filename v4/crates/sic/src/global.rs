//! Global/unified SIC search - fans a keyword query out across every
//! classification system `SicCatalog` currently has registered
//! (`lib.rs`'s `systems`), `UNION ALL`s them in one DataFusion query,
//! and tags each row with which system it came from. V3's equivalent
//! (`GET /V3.0/global/sic/description/{query_string}` ->
//! `UnifiedSICQueries.search_all_descriptions`, `lib/unified_sic.py:33-110+`)
//! did this by instantiating one query object per system and merging
//! in Python; this does the same fan-out-and-merge as a single SQL
//! statement instead (`docs/plans/sic-global-search.md`).
//!
//! Deliberately built from `SicCatalog::systems` at query time, not a
//! hardcoded list of tables - whichever systems are actually
//! registered (today: just US SIC and, once loaded, Japan SIC) are
//! exactly what gets searched, so this never references a table that
//! wasn't actually loaded at startup.
//!
//! Same raw field shape as `lookup::SicMatch`, plus `source_type`
//! (matching the UI's existing per-source label convention, e.g.
//! `result.source_type === 'Japan SIC'` in `static/index.html`) - kept
//! uniform across systems rather than inventing system-specific field
//! names here, so the frontend decides per `source_type` how to label
//! things, same as it already does for the single-system case.

use datafusion::arrow::array::{Float32Array, Float64Array};
use serde::Serialize;

use crate::embed::model_info;
use crate::similarity::format_float_array_literal;

#[derive(Debug, Clone, Serialize)]
pub struct GlobalSicMatch {
    pub source_type: String,
    pub section_id: String,
    pub section_desc: String,
    pub division_id: String,
    pub division_desc: String,
    pub group_id: String,
    pub group_desc: String,
    pub class_id: String,
    pub class_desc: String,
}

impl super::SicCatalog {
    /// Keyword search across every registered classification system.
    /// First of the three variants `sic-global-search.md` calls for
    /// (keyword/semantic/hybrid) - semantic global needs a decision on
    /// whether a single shared embedding space across systems is even
    /// valid (not yet answered), so it isn't built here.
    pub async fn find_by_description_global(
        &self,
        query: &str,
    ) -> anyhow::Result<Vec<GlobalSicMatch>> {
        if self.systems.is_empty() {
            return Ok(Vec::new());
        }

        let escaped = query.replace('\'', "''");
        let selects: Vec<String> = self
            .systems
            .iter()
            .map(|system| {
                let label = system.source_label.replace('\'', "''");
                // A plain string literal comes back as Utf8 (plain
                // StringArray), while every real column from the
                // feather file is LargeUtf8 (LargeStringArray, per the
                // source .feather's own schema) - arrow_cast forces
                // source_type to match, otherwise the downcast in
                // string_col() below panics on this column specifically.
                format!(
                    "SELECT DISTINCT arrow_cast('{label}', 'LargeUtf8') AS source_type, \
                     section_id, section_desc, division_id, division_desc, group_id, \
                     group_desc, class_id, class_desc \
                     FROM {table} WHERE class_desc ILIKE '%{escaped}%'",
                    table = system.table_name,
                )
            })
            .collect();
        let sql = selects.join(" UNION ALL ");

        let df = self.ctx.sql(&sql).await?;
        let batches = df.collect().await?;
        let mut out = Vec::new();
        for batch in &batches {
            let source_type = string_col(batch, "source_type");
            let section_id = string_col(batch, "section_id");
            let section_desc = string_col(batch, "section_desc");
            let division_id = string_col(batch, "division_id");
            let division_desc = string_col(batch, "division_desc");
            let group_id = string_col(batch, "group_id");
            let group_desc = string_col(batch, "group_desc");
            let class_id = string_col(batch, "class_id");
            let class_desc = string_col(batch, "class_desc");
            for i in 0..batch.num_rows() {
                out.push(GlobalSicMatch {
                    source_type: source_type.value(i).to_string(),
                    section_id: section_id.value(i).to_string(),
                    section_desc: section_desc.value(i).to_string(),
                    division_id: division_id.value(i).to_string(),
                    division_desc: division_desc.value(i).to_string(),
                    group_id: group_id.value(i).to_string(),
                    group_desc: group_desc.value(i).to_string(),
                    class_id: class_id.value(i).to_string(),
                    class_desc: class_desc.value(i).to_string(),
                });
            }
        }
        Ok(out)
    }

    /// Semantic search across every registered classification system -
    /// second of `sic-global-search.md`'s three variants. Each
    /// system's own top-k nearest neighbors are fetched first (a
    /// standard distributed-top-k argument: the globally-best k rows
    /// can only come from each shard's own locally-best k, so fetching
    /// k per shard before merging is both necessary and sufficient),
    /// then merged and re-sorted by distance. Relies on every
    /// registered system having been embedded with the *same* model
    /// (confirmed for Japan SIC - `tmp/japan_rev13_flat_embedded.feather`'s
    /// schema carries the identical `model`/`model_revision` metadata
    /// as US SIC's, so this isn't "comparing two different embedding
    /// spaces," it's the same model over two corpora - but this isn't
    /// re-verified at query time, so a future system embedded with a
    /// different model would silently produce a miscalibrated ranking
    /// rather than an error).
    pub async fn search_similar_global(
        &self,
        model_id: &str,
        query_vector: &[f32],
        k: usize,
    ) -> anyhow::Result<Vec<GlobalSearchHit>> {
        if self.systems.is_empty() {
            return Ok(Vec::new());
        }

        let info =
            model_info(model_id).ok_or_else(|| anyhow::anyhow!("unknown model id: {model_id}"))?;
        if query_vector.len() != info.dim {
            anyhow::bail!(
                "query vector dim {} does not match model dim {}",
                query_vector.len(),
                info.dim
            );
        }

        let vector_literal = format_float_array_literal(query_vector);
        let per_system: Vec<String> = self
            .systems
            .iter()
            .map(|system| {
                let label = system.source_label.replace('\'', "''");
                format!(
                    "(SELECT arrow_cast('{label}', 'LargeUtf8') AS source_type, unique_key, \
                     section_desc, division_desc, group_desc, class_desc, subclass_desc, \
                     array_distance({col}, arrow_cast({lit}, 'FixedSizeList({dim}, Float32)')) AS distance \
                     FROM {table} ORDER BY distance ASC LIMIT {k})",
                    col = info.vector_column,
                    lit = vector_literal,
                    dim = info.dim,
                    table = system.table_name,
                )
            })
            .collect();
        let sql = format!(
            "SELECT * FROM ({}) ORDER BY distance ASC LIMIT {k}",
            per_system.join(" UNION ALL "),
        );

        let results = self.ctx.sql(&sql).await?.collect().await?;

        let mut hits = Vec::with_capacity(k);
        let mut rank = 1usize;
        for batch in results {
            let source_type = string_col(&batch, "source_type");
            let unique_key = string_col(&batch, "unique_key");
            let section_desc = string_col(&batch, "section_desc");
            let division_desc = string_col(&batch, "division_desc");
            let group_desc = string_col(&batch, "group_desc");
            let class_desc = string_col(&batch, "class_desc");
            let subclass_desc = string_col(&batch, "subclass_desc");
            let distance_col = batch.column_by_name("distance").unwrap();

            for i in 0..batch.num_rows() {
                let dist: f32 =
                    if let Some(a) = distance_col.as_any().downcast_ref::<Float32Array>() {
                        a.value(i)
                    } else if let Some(a) = distance_col.as_any().downcast_ref::<Float64Array>() {
                        a.value(i) as f32
                    } else {
                        anyhow::bail!("distance column is neither Float32 nor Float64");
                    };
                let similarity = 1.0 - (dist * dist) / 2.0;
                hits.push(GlobalSearchHit {
                    rank,
                    similarity,
                    source_type: source_type.value(i).to_string(),
                    unique_key: unique_key.value(i).to_string(),
                    section_desc: section_desc.value(i).to_string(),
                    division_desc: division_desc.value(i).to_string(),
                    group_desc: group_desc.value(i).to_string(),
                    class_desc: class_desc.value(i).to_string(),
                    subclass_desc: subclass_desc.value(i).to_string(),
                });
                rank += 1;
            }
        }

        Ok(hits)
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct GlobalSearchHit {
    pub rank: usize,
    pub similarity: f32,
    pub source_type: String,
    pub unique_key: String,
    pub section_desc: String,
    pub division_desc: String,
    pub group_desc: String,
    pub class_desc: String,
    pub subclass_desc: String,
}

fn string_col<'a>(
    batch: &'a datafusion::arrow::record_batch::RecordBatch,
    name: &str,
) -> &'a datafusion::arrow::array::LargeStringArray {
    batch
        .column_by_name(name)
        .unwrap_or_else(|| panic!("missing column {name}"))
        .as_any()
        .downcast_ref::<datafusion::arrow::array::LargeStringArray>()
        .unwrap_or_else(|| panic!("column {name} is not LargeStringArray"))
}
