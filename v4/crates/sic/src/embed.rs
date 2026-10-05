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

    /// Embeds several texts in one call (one chunk each).
    pub fn embed_batch(&mut self, model_id: &str, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let model = self
            .models
            .get_mut(model_id)
            .ok_or_else(|| anyhow::anyhow!("unknown model id: {model_id}"))?;
        Ok(model.embed(texts, None)?)
    }

    /// Normalises `text`, splits it into sentence-window chunks sized by the
    /// model's own tokenizer, and works out where the model's input window
    /// would have cut it off (`company_match.rs`). The tokenizer is cloned
    /// once here, not once per sentence.
    pub fn prepare_text(&self, model_id: &str, text: &str) -> Result<crate::company_match::Prepared> {
        use crate::company_match as cm;
        let model = self
            .models
            .get(model_id)
            .ok_or_else(|| anyhow::anyhow!("unknown model id: {model_id}"))?;
        let max_length = model.tokenizer.get_truncation().map(|t| t.max_length).unwrap_or(usize::MAX);
        let mut tk = model.tokenizer.clone();
        tk.with_truncation(None)
            .map_err(|e| anyhow::anyhow!("failed to disable truncation for counting: {e}"))?;
        let count = |s: &str| tk.encode(s, true).map(|e| e.get_ids().len()).unwrap_or(0);

        let normalized = cm::normalize(text);
        let spans = cm::chunk_spans(&normalized, &count, cm::CHUNK_TARGET, cm::CHUNK_HARD_CAP);
        let chunks = spans
            .into_iter()
            .map(|span| cm::PreparedChunk { span, tokens: count(&normalized[span.start..span.end]) })
            .collect();

        let whole = tk
            .encode(normalized.as_str(), true)
            .map_err(|e| anyhow::anyhow!("tokenization failed: {e}"))?;
        let total_tokens = whole.get_ids().len();
        // The model keeps its first `max_length` ids including [CLS] and [SEP], so
        // the last real token it reads is at index max_length - 2.
        let truncation_at = if total_tokens > max_length && max_length >= 2 {
            whole.get_offsets().get(max_length - 2).map(|o| o.1).filter(|&o| normalized.is_char_boundary(o))
        } else {
            None
        };
        let mut phrases = cm::phrases(&normalized);
        phrases.truncate(cm::MAX_PHRASES);
        Ok(cm::Prepared { text: normalized, chunks, total_tokens, phrases, truncation_at })
    }

    /// The stepper's "re-match with the segments I kept": the caller supplies
    /// the chunks, so nothing is re-split. Each is normalised; empty ones are
    /// dropped; the "text" is the chunks joined by a space.
    pub fn prepare_chunks(&self, model_id: &str, chunks: &[String]) -> Result<crate::company_match::Prepared> {
        use crate::company_match as cm;
        let model = self
            .models
            .get(model_id)
            .ok_or_else(|| anyhow::anyhow!("unknown model id: {model_id}"))?;
        let mut tk = model.tokenizer.clone();
        tk.with_truncation(None)
            .map_err(|e| anyhow::anyhow!("failed to disable truncation for counting: {e}"))?;
        let count = |s: &str| tk.encode(s, true).map(|e| e.get_ids().len()).unwrap_or(0);

        let mut text = String::new();
        let mut prepared = Vec::new();
        for c in chunks.iter().map(|c| cm::normalize(c)).filter(|c| !c.is_empty()) {
            if !text.is_empty() {
                text.push(' ');
            }
            let start = text.len();
            text.push_str(&c);
            prepared.push(cm::PreparedChunk { span: cm::Span { start, end: text.len() }, tokens: count(&c) });
        }
        let total_tokens = count(&text);
        let mut phrases = cm::phrases(&text);
        phrases.truncate(cm::MAX_PHRASES);
        Ok(cm::Prepared { text, chunks: prepared, total_tokens, phrases, truncation_at: None })
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
