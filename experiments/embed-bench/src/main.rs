use anyhow::Result;
use fastembed::{EmbeddingModel, TextEmbedding, TextInitOptions};
use std::time::Instant;

// Benchmarks the 3 models fastembed-rs supports natively out of the box
// (all-MiniLM-L6-v2, all-mpnet-base-v2, BAAI/bge-small-en-v1.5) against
// real US SIC embedding_text values, to inform the low-dim/high-dim
// model pick for the company_dns Go/Rust rewrite (docs/plans/
// go-duckdb-rewrite.md). intfloat/e5-base-v2 is excluded - not in
// fastembed-rs's built-in catalog (confirmed separately).

fn read_embedding_texts(path: &str) -> Result<Vec<String>> {
    let content = std::fs::read_to_string(path)?;
    Ok(content.lines().map(|s| s.to_string()).collect())
}

fn bench_model(name: &str, model_variant: EmbeddingModel, texts: &[String]) -> Result<()> {
    println!("\n=== {name} ===");

    let load_start = Instant::now();
    let mut model = TextEmbedding::try_new(
        TextInitOptions::new(model_variant).with_show_download_progress(false),
    )?;
    let load_ms = load_start.elapsed().as_secs_f64() * 1000.0;
    println!("Model load/init time: {load_ms:.1}ms");

    // Warm-up (excludes first-call JIT/cache effects from the real measurement)
    let _ = model.embed(vec![texts[0].as_str()], None)?;

    // Single-query latency: simulates the actual runtime use case (embed
    // one incoming query string per request), not batch throughput.
    let n_single = 30;
    let mut single_latencies_ms = Vec::with_capacity(n_single);
    for i in 0..n_single {
        let text: &str = texts[i % texts.len()].as_str();
        let start = Instant::now();
        let _ = model.embed(vec![text], None)?;
        single_latencies_ms.push(start.elapsed().as_secs_f64() * 1000.0);
    }
    single_latencies_ms.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let median = single_latencies_ms[n_single / 2];
    let p95 = single_latencies_ms[(n_single as f64 * 0.95) as usize];
    let min = single_latencies_ms[0];
    let max = single_latencies_ms[n_single - 1];
    println!(
        "Single-query embed latency (n={n_single}): min={min:.2}ms median={median:.2}ms p95={p95:.2}ms max={max:.2}ms"
    );

    // Batch throughput: all 1,005 SIC rows in one call, for a sense of
    // offline/bulk-reembedding cost too (secondary to the runtime number
    // above, but a real data point for "how long would re-embedding the
    // whole corpus take").
    let batch_texts: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();
    let batch_start = Instant::now();
    let batch_embeddings = model.embed(batch_texts, None)?;
    let batch_ms = batch_start.elapsed().as_secs_f64() * 1000.0;
    let per_row_batch_ms = batch_ms / texts.len() as f64;
    println!(
        "Batch embed of {} rows: {batch_ms:.1}ms total, {per_row_batch_ms:.3}ms/row",
        texts.len()
    );

    println!("Output dimension: {}", batch_embeddings[0].len());

    Ok(())
}

fn main() -> Result<()> {
    // See ../README.md for how to generate embedding_texts.txt from a
    // real Mediumroast .feather file - not committed (derived data).
    let path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "embedding_texts.txt".to_string());
    let texts = read_embedding_texts(&path)?;
    println!("Loaded {} embedding_text values from {path}", texts.len());

    bench_model("all-MiniLM-L6-v2 (384-dim)", EmbeddingModel::AllMiniLML6V2, &texts)?;
    bench_model("BAAI/bge-small-en-v1.5 (384-dim)", EmbeddingModel::BGESmallENV15, &texts)?;
    bench_model("all-mpnet-base-v2 (768-dim)", EmbeddingModel::AllMpnetBaseV2, &texts)?;

    Ok(())
}
