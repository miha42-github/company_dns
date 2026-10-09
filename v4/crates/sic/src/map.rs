//! Map a chosen set of codes in one classification system into others
//! (`docs/plans/company-sic-match.md` sec. 11). No crosswalk tables are used (their
//! licensing is unresolved, so the product does not depend on them): every
//! target code is found by embedding similarity between the chosen codes'
//! descriptions and the target system's entries. When the company's description is
//! given, candidates are ranked by how well each fits it; without it, by
//! similarity to the source codes. Every result keeps which source codes it
//! came from.

use std::collections::{BTreeSet, HashMap};

use datafusion::arrow::array::{Array, FixedSizeListArray, Float32Array, LargeListArray, ListArray};
use serde::Serialize;

use crate::company_match::{choose, ChunkHit, Level, MAX_RECOMMENDED, POOL_PER_SYSTEM};
use crate::embed::model_info;

pub const MAX_ALTERNATIVES: usize = 10;
/// Per source code: how many of the most similar target entries to propose.
pub const NOMINEES_PER_CODE: usize = 5;
/// With a description: this many mapped codes are kept, and the set is filled
/// up to five from matching the description straight into the target system
/// (the variant that did best across all reviewed companies, `mapper_variants.py`).
pub const MAPPED_KEPT_WITH_DESCRIPTION: usize = 3;

#[derive(Debug, Clone, Serialize)]
pub struct MappedEntry {
    pub unique_key: String,
    pub code: String,
    pub title: String,
    pub hierarchy: Vec<Level>,
    /// Similarity used for ranking: best over the description's chunks when one
    /// was given, otherwise to the source code.
    pub similarity: f32,
    /// The source codes this one was reached from (empty when `basis` is `description`).
    pub from_codes: Vec<String>,
    /// `codes`: found from the codes you chose. `description`: found by matching the
    /// description directly into this system (fills the set when mapping alone gives fewer).
    pub basis: &'static str,
}

#[derive(Debug, Clone, Serialize)]
pub struct MappedSystem {
    pub system: String,
    pub recommended: Vec<MappedEntry>,
    pub alternatives: Vec<MappedEntry>,
    /// What the mapping did, in words.
    pub note: String,
}

struct Cand {
    from: BTreeSet<String>,
}

/// Pure ranking: candidates with scores in, recommended and alternatives out.
pub fn rank(mut scored: Vec<MappedEntry>) -> (Vec<MappedEntry>, Vec<MappedEntry>) {
    scored.sort_by(|a, b| b.similarity.partial_cmp(&a.similarity).unwrap_or(std::cmp::Ordering::Equal).then(a.unique_key.cmp(&b.unique_key)));
    let alternatives = if scored.len() > MAX_RECOMMENDED {
        scored.split_off(MAX_RECOMMENDED).into_iter().take(MAX_ALTERNATIVES).collect()
    } else {
        Vec::new()
    };
    (scored, alternatives)
}

/// First five recommended, the next ten alternatives, in the order given.
pub fn split_in_order(mut v: Vec<MappedEntry>) -> (Vec<MappedEntry>, Vec<MappedEntry>) {
    let alt = if v.len() > MAX_RECOMMENDED { v.split_off(MAX_RECOMMENDED).into_iter().take(MAX_ALTERNATIVES).collect() } else { Vec::new() };
    (v, alt)
}

impl super::SicCatalog {
    /// The embedding of one class in one system, or `None` when it is not there.
    pub async fn code_vector(&self, model_id: &str, label: &str, class_id: &str) -> anyhow::Result<Option<Vec<f32>>> {
        let info = model_info(model_id).ok_or_else(|| anyhow::anyhow!("unknown model id: {model_id}"))?;
        let Some(system) = self.systems.iter().find(|s| s.source_label == label) else {
            return Ok(None);
        };
        let sql = format!(
            "SELECT {col} AS v FROM {table} WHERE class_id = '{id}' LIMIT 1",
            col = info.vector_column,
            table = system.table_name,
            id = class_id.replace('\'', "''")
        );
        let batches = self.ctx.sql(&sql).await?.collect().await?;
        for batch in batches {
            if batch.num_rows() == 0 {
                continue;
            }
            let col = batch.column(0);
            let values = if let Some(a) = col.as_any().downcast_ref::<FixedSizeListArray>() {
                a.value(0)
            } else if let Some(a) = col.as_any().downcast_ref::<ListArray>() {
                a.value(0)
            } else if let Some(a) = col.as_any().downcast_ref::<LargeListArray>() {
                a.value(0)
            } else {
                anyhow::bail!("vector column has an unexpected type");
            };
            let f = values
                .as_any()
                .downcast_ref::<Float32Array>()
                .ok_or_else(|| anyhow::anyhow!("vector values are not Float32"))?;
            return Ok(Some(f.values().to_vec()));
        }
        Ok(None)
    }

    /// Map `codes` (class ids in system `from`) into each system in `to`.
    /// `description_vectors` are the embeddings of the description's chunks
    /// (empty when no description was given).
    pub async fn map_codes(
        &self,
        model_id: &str,
        from: &str,
        codes: &[String],
        to: &[String],
        description_vectors: &[Vec<f32>],
    ) -> anyhow::Result<Vec<MappedSystem>> {
        // source vectors, fetched once (used to rank without a description and for the fallback)
        let mut source: HashMap<String, Vec<f32>> = HashMap::new();
        for c in codes {
            if let Some(v) = self.code_vector(model_id, from, c).await? {
                source.insert(c.clone(), v);
            }
        }
        let mut out = Vec::new();
        for target in to {
            if target == from || !self.systems.iter().any(|s| &s.source_label == target) {
                continue;
            }
            let tl = [target.clone()];
            let mut cands: HashMap<String, Cand> = HashMap::new(); // class_id -> provenance
            for c in codes {
                if let Some(v) = source.get(c) {
                    let hits = self.search_systems(model_id, v, Some(&tl), None, NOMINEES_PER_CODE).await?;
                    for h in hits {
                        let id = h.levels.last().map(|l| l.id.clone()).unwrap_or_default();
                        cands.entry(id).or_insert(Cand { from: BTreeSet::new() }).from.insert(c.clone());
                    }
                }
            }
            if cands.is_empty() {
                out.push(MappedSystem { system: target.clone(), recommended: vec![], alternatives: vec![], note: format!("No counterparts found in {target}.") });
                continue;
            }
            let ids: Vec<String> = cands.keys().cloned().collect();
            // Two scores per candidate: similarity to the chosen codes, and (when there is a
            // description) its best fit to any chunk of it. Ranked by their mean, else by the first.
            let best_of = |hits: Vec<ChunkHit>, into: &mut HashMap<String, (f32, ChunkHit)>| {
                for h in hits {
                    let id = h.levels.last().map(|l| l.id.clone()).unwrap_or_default();
                    if into.get(&id).is_none_or(|(s, _)| h.similarity > *s) {
                        into.insert(id, (h.similarity, h));
                    }
                }
            };
            let mut src_best: HashMap<String, (f32, ChunkHit)> = HashMap::new();
            for v in source.values() {
                best_of(self.search_systems(model_id, v, Some(&tl), Some(&ids), ids.len()).await?, &mut src_best);
            }
            let mut fit_best: HashMap<String, (f32, ChunkHit)> = HashMap::new();
            for q in description_vectors {
                best_of(self.search_systems(model_id, q, Some(&tl), Some(&ids), ids.len()).await?, &mut fit_best);
            }
            let has_description = !description_vectors.is_empty();
            let mut scored: Vec<MappedEntry> = src_best
                .into_iter()
                .filter_map(|(id, (src, h))| {
                    let cand = cands.get(&id)?;
                    let fit = fit_best.get(&id).map(|(s, _)| *s).unwrap_or(src);
                    Some(MappedEntry {
                        unique_key: h.unique_key.clone(),
                        code: id,
                        title: h.levels.last().map(|l| l.description.clone()).unwrap_or_default(),
                        hierarchy: h.levels.clone(),
                        similarity: if has_description { (src + fit) / 2.0 } else { src },
                        from_codes: cand.from.iter().cloned().collect(),
                        basis: "codes",
                    })
                })
                .collect();
            if has_description {
                scored.sort_by(|a, b| b.similarity.partial_cmp(&a.similarity).unwrap_or(std::cmp::Ordering::Equal).then(a.unique_key.cmp(&b.unique_key)));
                let rest = scored.split_off(MAPPED_KEPT_WITH_DESCRIPTION.min(scored.len()));
                // fill: the description matched straight into this system
                let mut per_chunk = Vec::with_capacity(description_vectors.len());
                for q in description_vectors {
                    per_chunk.push(self.search_systems(model_id, q, Some(&tl), None, POOL_PER_SYSTEM).await?);
                }
                let direct = choose(&per_chunk, &[]).into_iter().next().map(|s| s.recommended).unwrap_or_default();
                let mut kept = scored;
                for e in direct {
                    if kept.len() >= MAX_RECOMMENDED {
                        break;
                    }
                    if !kept.iter().any(|k| k.unique_key == e.unique_key) {
                        kept.push(MappedEntry {
                            unique_key: e.unique_key,
                            code: e.code,
                            title: e.title,
                            hierarchy: e.hierarchy,
                            similarity: e.similarity,
                            from_codes: Vec::new(),
                            basis: "description",
                        });
                    }
                }
                // anything mapped but not kept becomes an alternative
                kept.extend(rest);
                scored = kept;
            }
            let total = scored.len();
            let (recommended, alternatives) = if has_description { split_in_order(scored) } else { rank(scored) };
            let basis = if has_description { "top three from your codes ranked by similarity and fit, the rest matched from the description" } else { "ranked by similarity to your codes" };
            out.push(MappedSystem {
                system: target.clone(),
                recommended,
                alternatives,
                note: format!("{total} candidate code(s) found by similarity to your codes; {basis}."),
            });
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn e(key: &str, sim: f32) -> MappedEntry {
        MappedEntry {
            unique_key: key.into(),
            code: key.into(),
            title: key.into(),
            hierarchy: vec![],
            similarity: sim,
            from_codes: vec![],
            basis: "codes",
        }
    }

    #[test]
    fn ranking_keeps_the_best_five_and_the_rest_as_alternatives() {
        let scored: Vec<MappedEntry> = (0..9).map(|i| e(&format!("c{i}"), 0.1 * i as f32)).collect();
        let (rec, alt) = rank(scored);
        assert_eq!(rec.len(), 5);
        assert_eq!(rec[0].unique_key, "c8");
        assert_eq!(alt.len(), 4);
        assert_eq!(alt[0].unique_key, "c3");
    }

    #[test]
    fn a_short_candidate_list_is_all_recommended() {
        let (rec, alt) = rank(vec![e("a", 0.2), e("b", 0.5)]);
        assert_eq!((rec.len(), alt.len()), (2, 0));
        assert_eq!(rec[0].unique_key, "b");
    }
}
