use anyhow::Result;
use fastembed::{EmbeddingModel, TextEmbedding, TextInitOptions};
use std::collections::HashMap;

/// The two models decided in docs/plans/go-duckdb-rewrite.md sec7.7, for
/// IC data specifically. Column names match tmp/us_flat_embedded.feather
/// exactly - see experiments/embed-bench and quality-eval for how those
/// got picked.
pub const MODEL_IDS: [&str; 2] = ["all_minilm_l6_v2", "all_mpnet_base_v2"];

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
    pub fn load() -> Result<Self> {
        let mut models = HashMap::new();
        models.insert(
            "all_minilm_l6_v2",
            TextEmbedding::try_new(
                TextInitOptions::new(EmbeddingModel::AllMiniLML6V2)
                    .with_show_download_progress(false),
            )?,
        );
        models.insert(
            "all_mpnet_base_v2",
            TextEmbedding::try_new(
                TextInitOptions::new(EmbeddingModel::AllMpnetBaseV2)
                    .with_show_download_progress(false),
            )?,
        );
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
