use anyhow::Result;
use fastembed::{EmbeddingModel, TextEmbedding, TextInitOptions};
use std::collections::HashMap;

/// Both remain recognized (see model_info below) even though only
/// all-MiniLM-L6-v2 loads by default - go-duckdb-rewrite.md sec7.8
/// dropped all-mpnet-base-v2 for IC data (lost on every quality metric
/// in sec7.6 *and* cost ~484MB extra RSS for no benefit), but main.rs's
/// IC_MODELS env var can still load it for comparison. Column names
/// match tmp/us_flat_embedded.feather exactly - see experiments/
/// embed-bench and quality-eval for how the pick got made.
pub struct ModelInfo {
    pub label: &'static str,
    pub dim: usize,
    pub vector_column: &'static str,
}

pub fn model_info(id: &str) -> Option<ModelInfo> {
    match id {
        "all_minilm_l6_v2" => Some(ModelInfo {
            label: "all-MiniLM-L6-v2 (384-dim, fast, best quality on this dataset)",
            dim: 384,
            vector_column: "vector_all_minilm_l6_v2",
        }),
        "all_mpnet_base_v2" => Some(ModelInfo {
            label: "all-mpnet-base-v2 (768-dim, higher-dim baseline)",
            dim: 768,
            vector_column: "vector_all_mpnet_base_v2",
        }),
        _ => None,
    }
}

/// Both models loaded once at startup - load times are ~70-150ms each
/// (experiments/embed-bench), trivial next to a service's lifetime.
pub struct Embedders {
    models: HashMap<&'static str, TextEmbedding>,
}

impl Embedders {
    /// Loads only the given model ids - lets main.rs control this via
    /// an env var, e.g. for the memory-footprint comparison in
    /// docs/plans/go-duckdb-rewrite.md sec7.8 (one model vs. two).
    pub fn load(ids: &[&'static str]) -> Result<Self> {
        let mut models = HashMap::new();
        for id in ids {
            let variant = match *id {
                "all_minilm_l6_v2" => EmbeddingModel::AllMiniLML6V2,
                "all_mpnet_base_v2" => EmbeddingModel::AllMpnetBaseV2,
                other => anyhow::bail!("unknown model id: {other}"),
            };
            let model = TextEmbedding::try_new(
                TextInitOptions::new(variant).with_show_download_progress(false),
            )?;
            models.insert(*id, model);
        }
        Ok(Self { models })
    }

    /// Embeds a single query string with the named model. Neither model
    /// needs a prefix convention (see docs/plans/go-duckdb-rewrite.md's
    /// per-model prefix table) - unlike e5-base-v2, which isn't one of
    /// the two models this service supports.
    pub fn embed_query(&mut self, model_id: &str, text: &str) -> Result<Vec<f32>> {
        let model = self
            .models
            .get_mut(model_id)
            .ok_or_else(|| anyhow::anyhow!("unknown model id: {model_id}"))?;
        let embeddings = model.embed(vec![text], None)?;
        Ok(embeddings.into_iter().next().unwrap())
    }
}
