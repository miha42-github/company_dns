//! Hybrid (keyword + semantic) SIC search across every registered
//! classification system, fused with Reciprocal Rank Fusion (RRF) in one
//! DataFusion SQL statement (`docs/plans/sic-hybrid-search.md`).
//!
//! Two ranked lists are built over the merged systems and fused:
//!
//! * **keyword** - every class whose `class_desc` contains the query
//!   (case-insensitive substring), ranked by where the match starts
//!   (`strpos`, earlier is better) with ties sharing a rank (`RANK()`).
//!   There is no relevance signal beyond that; a real BM25-style score
//!   would need a UDF and was measured as unnecessary (plan section 3).
//! * **semantic** - the global top [`CANDIDATE_POOL`] rows by embedding
//!   distance (each system's own top-N first, then merged, the same
//!   distributed-top-k argument `global.rs` uses), ranked by distance.
//!
//! `rrf_score = 1/(RRF_K + keyword_rank) + 1/(RRF_K + semantic_rank)`, each
//! term only present when the engine surfaced the row. A row found by one
//! engine keeps a nonzero score (decision 1 in the plan). Rows are joined on
//! `unique_key`, never `class_id`: a class id such as `0111` exists in
//! several systems.
//!
//! The keyword predicate is `strpos(lower(class_desc), lower(query)) > 0`,
//! not `ILIKE '%query%'`, so `%` and `_` in the user's text are literal
//! characters and cannot act as wildcards.

use datafusion::arrow::array::{Array, Float64Array, Int64Array};
use serde::Serialize;

use crate::embed::model_info;
use crate::similarity::format_float_array_literal;

/// The standard constant from the original RRF paper. Measured against 20 in
/// the plan's offline check: no meaningful difference.
pub const RRF_K: u32 = 60;

/// How many semantic neighbours enter the fusion. Wider than the largest
/// `k` (50) so fusion has something real to rerank. 100 was measured against
/// 50 and made no difference.
pub const CANDIDATE_POOL: usize = 50;

#[derive(Debug, Clone, Serialize)]
pub struct HybridHit {
    pub rank: usize,
    pub rrf_score: f64,
    pub source_type: String,
    pub unique_key: String,
    pub section_desc: String,
    pub division_desc: String,
    pub group_desc: String,
    pub class_desc: String,
    /// `None` = the keyword engine did not surface this row.
    pub keyword_rank: Option<usize>,
    /// `None` = the semantic engine did not surface this row.
    pub semantic_rank: Option<usize>,
    /// Raw cosine similarity, present only when `semantic_rank` is.
    pub similarity: Option<f32>,
    /// Which engines found it: `["keyword"]`, `["semantic"]` or both.
    pub engines: Vec<&'static str>,
}

impl super::SicCatalog {
    /// Hybrid search over every registered system. `k` rows are returned
    /// (the caller clamps it); the semantic side always uses
    /// [`CANDIDATE_POOL`] candidates regardless of `k`.
    pub async fn search_hybrid_global(
        &self,
        model_id: &str,
        query: &str,
        query_vector: &[f32],
        k: usize,
    ) -> anyhow::Result<Vec<HybridHit>> {
        let info =
            model_info(model_id).ok_or_else(|| anyhow::anyhow!("unknown model id: {model_id}"))?;
        if query_vector.len() != info.dim {
            anyhow::bail!(
                "query vector dim {} does not match model dim {}",
                query_vector.len(),
                info.dim
            );
        }
        self.run_hybrid(info.vector_column, info.dim, query, query_vector, k, CANDIDATE_POOL)
            .await
    }

    /// The executing core, with the vector column, dimension and pool size
    /// as parameters so tests can run the real SQL on tiny in-memory tables.
    pub(crate) async fn run_hybrid(
        &self,
        vector_column: &str,
        dim: usize,
        query: &str,
        query_vector: &[f32],
        k: usize,
        pool: usize,
    ) -> anyhow::Result<Vec<HybridHit>> {
        if self.systems.is_empty() || query.trim().is_empty() {
            return Ok(Vec::new());
        }
        let systems: Vec<(&str, &str)> = self
            .systems
            .iter()
            .map(|s| (s.table_name.as_str(), s.source_label.as_str()))
            .collect();
        let sql = build_hybrid_sql(&systems, query, query_vector, vector_column, dim, k, pool);

        let batches = self.ctx.sql(&sql).await?.collect().await?;
        let mut hits = Vec::new();
        let mut rank = 1usize;
        for batch in &batches {
            let source_type = string_col(batch, "h_source");
            let unique_key = string_col(batch, "h_key");
            let section_desc = string_col(batch, "h_section");
            let division_desc = string_col(batch, "h_division");
            let group_desc = string_col(batch, "h_group");
            let class_desc = string_col(batch, "h_class");
            let kw_rank = int_col(batch, "kw_rank");
            let sem_rank = int_col(batch, "sem_rank");
            let similarity = float_col(batch, "similarity");
            let rrf = float_col(batch, "rrf_score");
            for i in 0..batch.num_rows() {
                let keyword_rank = (!kw_rank.is_null(i)).then(|| kw_rank.value(i) as usize);
                let semantic_rank = (!sem_rank.is_null(i)).then(|| sem_rank.value(i) as usize);
                let mut engines = Vec::new();
                if keyword_rank.is_some() {
                    engines.push("keyword");
                }
                if semantic_rank.is_some() {
                    engines.push("semantic");
                }
                hits.push(HybridHit {
                    rank,
                    rrf_score: rrf.value(i),
                    source_type: source_type.value(i).to_string(),
                    unique_key: unique_key.value(i).to_string(),
                    section_desc: section_desc.value(i).to_string(),
                    division_desc: division_desc.value(i).to_string(),
                    group_desc: group_desc.value(i).to_string(),
                    class_desc: class_desc.value(i).to_string(),
                    keyword_rank,
                    semantic_rank,
                    similarity: (!similarity.is_null(i)).then(|| similarity.value(i) as f32),
                    engines,
                });
                rank += 1;
            }
        }
        Ok(hits)
    }
}

/// Builds the one SQL statement. `systems` is `(table_name, source_label)`
/// per registered system; the per-system `SELECT`s are joined with
/// `UNION ALL` exactly as in `global.rs`, so only registered tables are
/// referenced.
pub(crate) fn build_hybrid_sql(
    systems: &[(&str, &str)],
    query: &str,
    query_vector: &[f32],
    vector_column: &str,
    dim: usize,
    k: usize,
    pool: usize,
) -> String {
    // Only single quotes need handling: the keyword predicate is strpos(),
    // not LIKE, so `%` and `_` are ordinary characters.
    let q = query.replace('\'', "''");
    let lit = format_float_array_literal(query_vector);

    let kw_src: Vec<String> = systems
        .iter()
        .map(|(table, label)| {
            let label = label.replace('\'', "''");
            // arrow_cast: a bare string literal is Utf8, every feather column
            // is LargeUtf8; without the cast the LargeStringArray downcast
            // below panics on source_type (same gotcha as global.rs).
            format!(
                "SELECT DISTINCT arrow_cast('{label}', 'LargeUtf8') AS source_type, unique_key, \
                 section_desc, division_desc, group_desc, class_desc, \
                 strpos(lower(class_desc), lower('{q}')) AS match_pos \
                 FROM {table} WHERE strpos(lower(class_desc), lower('{q}')) > 0"
            )
        })
        .collect();

    let sem_src: Vec<String> = systems
        .iter()
        .map(|(table, label)| {
            let label = label.replace('\'', "''");
            format!(
                "(SELECT arrow_cast('{label}', 'LargeUtf8') AS source_type, unique_key, \
                 section_desc, division_desc, group_desc, class_desc, \
                 array_distance({vector_column}, arrow_cast({lit}, 'FixedSizeList({dim}, Float32)')) AS distance \
                 FROM {table} ORDER BY distance ASC LIMIT {pool})"
            )
        })
        .collect();

    format!(
        "WITH kw_src AS ({kw_union}), \
         kw AS (SELECT source_type, unique_key, section_desc, division_desc, group_desc, class_desc, \
                RANK() OVER (ORDER BY match_pos ASC) AS kw_rank FROM kw_src), \
         sem_src AS ({sem_union}), \
         sem AS (SELECT source_type, unique_key, section_desc, division_desc, group_desc, class_desc, distance, \
                 RANK() OVER (ORDER BY distance ASC) AS sem_rank \
                 FROM (SELECT * FROM sem_src ORDER BY distance ASC LIMIT {pool})) \
         SELECT * FROM ( \
           SELECT COALESCE(kw.source_type, sem.source_type) AS h_source, \
                  COALESCE(kw.unique_key, sem.unique_key) AS h_key, \
                  COALESCE(kw.section_desc, sem.section_desc) AS h_section, \
                  COALESCE(kw.division_desc, sem.division_desc) AS h_division, \
                  COALESCE(kw.group_desc, sem.group_desc) AS h_group, \
                  COALESCE(kw.class_desc, sem.class_desc) AS h_class, \
                  CAST(kw.kw_rank AS BIGINT) AS kw_rank, \
                  CAST(sem.sem_rank AS BIGINT) AS sem_rank, \
                  1.0 - (CAST(sem.distance AS DOUBLE) * CAST(sem.distance AS DOUBLE)) / 2.0 AS similarity, \
                  COALESCE(1.0 / ({RRF_K} + CAST(kw.kw_rank AS DOUBLE)), 0.0) \
                    + COALESCE(1.0 / ({RRF_K} + CAST(sem.sem_rank AS DOUBLE)), 0.0) AS rrf_score \
           FROM kw FULL OUTER JOIN sem ON kw.unique_key = sem.unique_key \
         ) ORDER BY rrf_score DESC, sem_rank ASC NULLS LAST, h_key ASC LIMIT {k}",
        kw_union = kw_src.join(" UNION ALL "),
        sem_union = sem_src.join(" UNION ALL "),
    )
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

fn int_col<'a>(batch: &'a datafusion::arrow::record_batch::RecordBatch, name: &str) -> &'a Int64Array {
    batch
        .column_by_name(name)
        .unwrap_or_else(|| panic!("missing column {name}"))
        .as_any()
        .downcast_ref::<Int64Array>()
        .unwrap_or_else(|| panic!("column {name} is not Int64Array"))
}

fn float_col<'a>(
    batch: &'a datafusion::arrow::record_batch::RecordBatch,
    name: &str,
) -> &'a Float64Array {
    batch
        .column_by_name(name)
        .unwrap_or_else(|| panic!("missing column {name}"))
        .as_any()
        .downcast_ref::<Float64Array>()
        .unwrap_or_else(|| panic!("column {name} is not Float64Array"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{SicCatalog, SicSystem};
    use datafusion::arrow::array::{FixedSizeListArray, Float32Array, LargeStringArray};
    use datafusion::arrow::datatypes::{DataType, Field, Schema};
    use datafusion::arrow::record_batch::RecordBatch;
    use datafusion::datasource::MemTable;
    use datafusion::prelude::SessionContext;
    use std::sync::Arc;

    /// (class_id, class_desc, 3-d vector)
    type Row<'a> = (&'a str, &'a str, [f32; 3]);

    /// One tiny system.
    fn system_table(module: &str, rows: &[Row]) -> Arc<MemTable> {
        let field = Arc::new(Field::new("item", DataType::Float32, true));
        let schema = Arc::new(Schema::new(vec![
            Field::new("unique_key", DataType::LargeUtf8, false),
            Field::new("section_desc", DataType::LargeUtf8, false),
            Field::new("division_desc", DataType::LargeUtf8, false),
            Field::new("group_desc", DataType::LargeUtf8, false),
            Field::new("class_desc", DataType::LargeUtf8, false),
            Field::new("vec", DataType::FixedSizeList(field.clone(), 3), false),
        ]));
        let s = |f: &dyn Fn(&Row) -> String| {
            Arc::new(LargeStringArray::from(rows.iter().map(f).collect::<Vec<_>>()))
        };
        let flat: Vec<f32> = rows.iter().flat_map(|r| r.2).collect();
        let vecs = FixedSizeListArray::try_new(field, 3, Arc::new(Float32Array::from(flat)), None).unwrap();
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                s(&|r| format!("{module}-A-01-011-{}", r.0)),
                s(&|_| "Section".to_string()),
                s(&|_| "Division".to_string()),
                s(&|_| "Group".to_string()),
                s(&|r| r.1.to_string()),
                Arc::new(vecs),
            ],
        )
        .unwrap();
        Arc::new(MemTable::try_new(schema, vec![vec![batch]]).unwrap())
    }

    fn catalog() -> SicCatalog {
        let ctx = SessionContext::new();
        // Same class id "0111" in both systems on purpose: the join key must
        // be unique_key, not class_id.
        ctx.register_table(
            "t_us",
            system_table(
                "us",
                &[
                    ("0111", "Growing of wheat and grain", [1.0, 0.0, 0.0]),
                    ("0112", "Cattle ranching", [0.0, 1.0, 0.0]),
                    ("0113", "Wheat flour milling", [0.0, 0.0, 1.0]),
                ],
            ),
        )
        .unwrap();
        ctx.register_table(
            "t_eu",
            system_table(
                "nace",
                &[
                    ("0111", "Growing of cereals", [0.9, 0.1, 0.0]),
                    ("0114", "100%_literal marker", [0.0, 0.0, -1.0]),
                ],
            ),
        )
        .unwrap();
        SicCatalog {
            ctx,
            systems: vec![
                SicSystem { table_name: "t_us".into(), source_label: "US SIC".into() },
                SicSystem { table_name: "t_eu".into(), source_label: "EU NACE".into() },
            ],
        }
    }

    #[test]
    fn sql_references_exactly_the_registered_systems() {
        let two = build_hybrid_sql(&[("a", "A"), ("b", "B")], "x", &[0.0, 1.0], "v", 2, 10, 50);
        assert!(two.contains("FROM a ") && two.contains("FROM b "));
        assert_eq!(two.matches("UNION ALL").count(), 2); // one in kw_src, one in sem_src
        let one = build_hybrid_sql(&[("a", "A")], "x", &[0.0, 1.0], "v", 2, 10, 50);
        assert!(!one.contains("UNION ALL") && !one.contains("FROM b "));
    }

    #[test]
    fn sql_escapes_quotes_and_does_not_use_like() {
        let sql = build_hybrid_sql(&[("a", "O'Brien SIC")], "it's", &[0.0], "v", 1, 10, 50);
        assert!(sql.contains("lower('it''s')") && sql.contains("'O''Brien SIC'"));
        assert!(!sql.to_uppercase().contains("ILIKE") && !sql.contains(" LIKE "));
    }

    #[tokio::test]
    async fn fuses_both_engines_and_joins_on_unique_key() {
        let cat = catalog();
        // Query "wheat", vector nearest US 0111 (growing of wheat, [1,0,0]).
        // pool=2: semantic list is only the 2 nearest rows overall.
        let hits = cat.run_hybrid("vec", 3, "wheat", &[1.0, 0.0, 0.0], 10, 2).await.unwrap();
        let by = |key: &str| hits.iter().find(|h| h.unique_key == key).unwrap().clone();

        // Found by both engines -> first, with both ranks and a similarity.
        let both = by("us-A-01-011-0111");
        assert_eq!(hits[0].unique_key, both.unique_key);
        assert_eq!(both.engines, vec!["keyword", "semantic"]);
        assert_eq!(both.semantic_rank, Some(1));
        assert!(both.similarity.unwrap() > 0.99);

        // Keyword-only (substring match, outside the semantic pool).
        let kw_only = by("us-A-01-011-0113");
        assert_eq!(kw_only.engines, vec!["keyword"]);
        assert!(kw_only.semantic_rank.is_none() && kw_only.similarity.is_none());

        // Semantic-only (no "wheat" in "Growing of cereals", but a near vector).
        let sem_only = by("nace-A-01-011-0111");
        assert_eq!(sem_only.engines, vec!["semantic"]);
        assert!(sem_only.keyword_rank.is_none());

        // Same class_id "0111" in two systems stayed two distinct hits.
        assert_ne!(both.unique_key, sem_only.unique_key);
        // Ranks are 1..n in order; scores never increase down the list.
        for (i, h) in hits.iter().enumerate() {
            assert_eq!(h.rank, i + 1);
        }
        assert!(hits.windows(2).all(|w| w[0].rrf_score >= w[1].rrf_score));
    }

    #[tokio::test]
    async fn keyword_ties_share_a_rank_and_earlier_match_wins() {
        let cat = catalog();
        // "wheat": US 0111 matches at position 12, US 0113 at position 1.
        let hits = cat.run_hybrid("vec", 3, "wheat", &[0.0, 1.0, 0.0], 10, 1).await.unwrap();
        let flour = hits.iter().find(|h| h.unique_key == "us-A-01-011-0113").unwrap();
        let grow = hits.iter().find(|h| h.unique_key == "us-A-01-011-0111").unwrap();
        assert_eq!(flour.keyword_rank, Some(1));
        assert_eq!(grow.keyword_rank, Some(2));
    }

    #[tokio::test]
    async fn wildcards_in_the_query_are_literal_and_blank_queries_are_empty() {
        let cat = catalog();
        // "%_" would match everything under LIKE; as a literal it matches
        // only the one description containing it.
        let hits = cat.run_hybrid("vec", 3, "%_", &[1.0, 0.0, 0.0], 10, 1).await.unwrap();
        let kw: Vec<_> = hits.iter().filter(|h| h.keyword_rank.is_some()).collect();
        assert_eq!(kw.len(), 1);
        assert_eq!(kw[0].class_desc, "100%_literal marker");
        assert!(cat.run_hybrid("vec", 3, "   ", &[1.0, 0.0, 0.0], 10, 1).await.unwrap().is_empty());
    }

    #[tokio::test]
    async fn k_limits_results_and_empty_catalog_is_empty() {
        let cat = catalog();
        assert_eq!(cat.run_hybrid("vec", 3, "wheat", &[1.0, 0.0, 0.0], 2, 5).await.unwrap().len(), 2);
        let empty = SicCatalog { ctx: SessionContext::new(), systems: vec![] };
        assert!(empty.run_hybrid("vec", 3, "x", &[1.0, 0.0, 0.0], 5, 5).await.unwrap().is_empty());
    }
}
