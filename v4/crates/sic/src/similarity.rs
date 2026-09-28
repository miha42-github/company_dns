//! Vector similarity search over US SIC data - promoted from
//! `experiments/ic-similarity-service/src/search.rs`, unchanged in
//! substance. Backs `company-dns-server`'s new
//! `GET /V4.0/na/sic/similarity/{query}` endpoint
//! (`docs/plans/v4-server-prototype.md` §5.1) - V3 has no equivalent.

use anyhow::Result;
use datafusion::arrow::array::{Float32Array, Float64Array, LargeStringArray};
use serde::Serialize;

use crate::embed::model_info;

#[derive(Serialize, Clone)]
pub struct SearchHit {
    pub rank: usize,
    pub similarity: f32,
    pub unique_key: String,
    pub section_desc: String,
    pub division_desc: String,
    pub group_desc: String,
    pub class_desc: String,
    pub subclass_desc: String,
}

impl super::SicCatalog {
    /// Ranks all rows by similarity to `query_vector` under the given
    /// model's vector column, returns the top k. Goes through
    /// DataFusion's SQL path deliberately (`array_distance`'s Rust
    /// builder API mismatch, `go-duckdb-rewrite.md` §7.3). Vectors are
    /// pre-normalized, so ascending Euclidean distance gives the
    /// identical ranking as descending cosine similarity; converted
    /// back to a similarity score for display.
    pub async fn search_similar(
        &self,
        model_id: &str,
        query_vector: &[f32],
        k: usize,
    ) -> Result<Vec<SearchHit>> {
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
        let sql = format!(
            "SELECT unique_key, section_desc, division_desc, group_desc, class_desc, subclass_desc, \
             array_distance({col}, arrow_cast({lit}, 'FixedSizeList({dim}, Float32)')) AS distance \
             FROM sic_data \
             ORDER BY distance ASC \
             LIMIT {k}",
            col = info.vector_column,
            lit = vector_literal,
            dim = info.dim,
        );

        let results = self.ctx.sql(&sql).await?.collect().await?;

        let mut hits = Vec::with_capacity(k);
        let mut rank = 1usize;
        for batch in results {
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
                hits.push(SearchHit {
                    rank,
                    similarity,
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

fn string_col<'a>(
    batch: &'a datafusion::arrow::record_batch::RecordBatch,
    name: &str,
) -> &'a LargeStringArray {
    batch
        .column_by_name(name)
        .unwrap_or_else(|| panic!("missing column {name}"))
        .as_any()
        .downcast_ref::<LargeStringArray>()
        .unwrap_or_else(|| panic!("column {name} is not LargeStringArray"))
}

fn format_float_array_literal(values: &[f32]) -> String {
    let parts: Vec<String> = values.iter().map(|v| format!("{v}")).collect();
    format!("[{}]", parts.join(","))
}
