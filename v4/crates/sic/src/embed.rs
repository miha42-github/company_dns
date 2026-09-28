//! Promoted from `experiments/ic-similarity-service/src/embed.rs`,
//! unchanged - `go-duckdb-rewrite.md` §7.8's decision (`all-MiniLM-
//! L6-v2` only for IC data) is what `company-dns-server` loads by
//! default; `all-mpnet-base-v2` stays recognized for comparison.

use anyhow::Result;
use fastembed::{EmbeddingModel, TextEmbedding, TextInitOptions};
use std::collections::HashMap;

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

pub struct Embedders {
    models: HashMap<&'static str, TextEmbedding>,
}

impl Embedders {
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

    pub fn embed_query(&mut self, model_id: &str, text: &str) -> Result<Vec<f32>> {
        let model = self
            .models
            .get_mut(model_id)
            .ok_or_else(|| anyhow::anyhow!("unknown model id: {model_id}"))?;
        let embeddings = model.embed(vec![text], None)?;
        Ok(embeddings.into_iter().next().unwrap())
    }

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
