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

    /// Real token count vs. the model's own max_length, BEFORE any
    /// truncation - lets callers warn when a query will be silently
    /// cut short. Confirmed this is a real problem, not theoretical:
    /// a 469-token company description against all-MiniLM-L6-v2's
    /// 256-token limit dropped 213 tokens (45%) including the entire
    /// final paragraph, changing the top search result (see chat log /
    /// docs/plans/ic-similarity-search-poc.md around 2026-09-27).
    ///
    /// Clones the tokenizer to disable its baked-in truncation for this
    /// one count - `Tokenizer` is cheap to clone (it's the same pattern
    /// the tokenizers crate itself uses internally for this purpose).
    pub fn token_info(&self, model_id: &str, text: &str) -> Result<TokenInfo> {
        let model = self
            .models
            .get(model_id)
            .ok_or_else(|| anyhow::anyhow!("unknown model id: {model_id}"))?;

        let max_length = model
            .tokenizer
            .get_truncation()
            .map(|t| t.max_length)
            .unwrap_or(usize::MAX);

        let mut untruncated = model.tokenizer.clone();
        untruncated
            .with_truncation(None)
            .map_err(|e| anyhow::anyhow!("failed to disable truncation for counting: {e}"))?;
        let encoding = untruncated
            .encode(text, true)
            .map_err(|e| anyhow::anyhow!("tokenization failed: {e}"))?;

        Ok(TokenInfo {
            actual_tokens: encoding.get_ids().len(),
            max_tokens: max_length,
        })
    }
}

pub struct TokenInfo {
    pub actual_tokens: usize,
    pub max_tokens: usize,
}

impl TokenInfo {
    pub fn truncated(&self) -> bool {
        self.actual_tokens > self.max_tokens
    }
}
