//! Company description -> a recommended SET of industry codes, per system
//! (`docs/plans/company-sic-match.md`, decision 9: a company has a set of
//! codes, not one; the product answer is 2-5 per system with their hierarchy).
//!
//! Pipeline: normalise the text, split it into sentence-window chunks (the
//! model only reads 256 word pieces and was trained at 128, so long text is
//! chunked, not truncated), embed each chunk, search every registered system
//! per chunk, then choose per system:
//!
//! * `recommended` - 2 to 5 codes. Each chunk nominates its best codes (two,
//!   or more when there are only a few chunks);
//!   codes are ranked by the summed similarity of their nominations, then by best
//!   similarity. This is what makes a multi-business company (Apple, P&G,
//!   Hitachi) return several lines of business instead of one winner. Padded
//!   from the best-scoring codes up to the floor of 2.
//! * `alternatives` - the next few candidates, for a person to pick from.
//!
//! The chunker mirrors `experiments/company-sic-eval/chunker.py` (the spec)
//! and the selection rule is the one chosen in `select_eval.py`
//! ("chunk winners x2"). No LLM: this is retrieval plus a rule, and the
//! response says so (`limitations`).

use std::collections::HashMap;

use datafusion::arrow::array::{Float32Array, Float64Array, LargeStringArray};
use serde::Serialize;

use crate::embed::model_info;
use crate::similarity::format_float_array_literal;

/// The classification systems' labels, as the server registers them.
pub const US: &str = "US SIC";
pub const ISIC: &str = "ISIC";
pub const NACE: &str = "EU NACE";
pub const JAPAN: &str = "Japan SIC";

pub const CHUNK_TARGET: usize = 64;
pub const CHUNK_HARD_CAP: usize = 200;
pub const MAX_CHUNKS: usize = 16;
pub const MIN_RECOMMENDED: usize = 2;
pub const MAX_RECOMMENDED: usize = 5;
pub const ALTERNATIVES: usize = 7;
/// Each chunk nominates at least this many codes; fewer chunks nominate more
/// (see `nominees_per_chunk`) so one short multi-business paragraph still
/// yields a set.
pub const MIN_NOMINEES_PER_CHUNK: usize = 2;
pub const POOL_PER_SYSTEM: usize = 50;
/// How many codes each chunk nominates: enough that all the chunks together
/// can fill the largest set, never fewer than the minimum.
pub fn nominees_per_chunk(chunks: usize) -> usize {
    let n = chunks.max(1);
    MAX_RECOMMENDED.div_ceil(n).clamp(MIN_NOMINEES_PER_CHUNK, MAX_RECOMMENDED)
}

/// A key phrase nominates its best code only at or above this similarity.
pub const PHRASE_MIN: f32 = 0.40;
/// At most this many key phrases are queried.
pub const MAX_PHRASES: usize = 24;

/// Below this best similarity a system's answer is flagged as a weak match.
pub const WEAK_MATCH_BELOW: f32 = 0.30;
/// Fewer word pieces than this is not enough text to say much.
pub const SHORT_INPUT_BELOW: usize = 30;

// ---------------------------------------------------------------- chunker

/// A byte range of the normalised text.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Span {
    pub start: usize,
    pub end: usize,
}

const ABBREV: &[&str] = &[
    "inc", "corp", "co", "ltd", "llc", "plc", "u.s", "u.k", "st", "no", "mr", "mrs", "ms", "dr", "jr", "sr", "vs",
    "etc", "e.g", "i.e", "approx", "dept", "est", "bros", "intl", "mt", "ft",
];

/// Collapses all whitespace runs to one space and trims. Every offset in this
/// module refers to this normalised string.
pub fn normalize(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn is_closer(c: char) -> bool {
    matches!(c, '"' | '\'' | ')' | ']')
}

/// True when the text at `idx` can start a new sentence: an optional opening
/// quote or bracket, then an ASCII capital or digit.
fn starts_sentence(rest: &str) -> bool {
    let mut it = rest.chars();
    let first = it.next();
    let c = match first {
        Some('"') | Some('\'') | Some('(') | Some('[') => it.next(),
        other => other,
    };
    matches!(c, Some(c) if c.is_ascii_uppercase() || c.is_ascii_digit())
}

/// Splits normalised text into sentences, not splitting after common
/// abbreviations ("Inc.", "U.S.") or a lone initial ("J. Smith").
pub fn split_sentences(text: &str) -> Vec<Span> {
    let mut out = Vec::new();
    let mut start = 0usize;
    let bytes: Vec<(usize, char)> = text.char_indices().collect();
    let mut i = 0usize;
    while i < bytes.len() {
        let c = bytes[i].1;
        if matches!(c, '.' | '!' | '?') {
            // punctuation, then closers, then whitespace, then a sentence start
            let mut j = i + 1;
            while j < bytes.len() && is_closer(bytes[j].1) {
                j += 1;
            }
            if j < bytes.len() && bytes[j].1.is_whitespace() {
                let after_ws = bytes[j].0 + bytes[j].1.len_utf8();
                if starts_sentence(&text[after_ws..]) {
                    let piece_end = bytes[j].0;
                    let piece = &text[start..piece_end];
                    let mut skip = false;
                    if c == '.' {
                        let trimmed = piece.trim_end_matches(|ch: char| matches!(ch, '.' | '!' | '?') || is_closer(ch));
                        let last = trimmed.split_whitespace().last().unwrap_or("").to_lowercase();
                        let last = last.trim_start_matches('(');
                        let single_letter = last.len() == 1 && last.chars().all(|ch| ch.is_ascii_lowercase());
                        skip = ABBREV.contains(&last) || single_letter;
                    }
                    if !skip {
                        out.push(Span { start, end: piece_end });
                        start = after_ws;
                    }
                    i = j + 1;
                    continue;
                }
            }
        }
        i += 1;
    }
    if start < text.len() {
        out.push(Span { start, end: text.len() });
    }
    out
}

/// Splits one over-long sentence at clause marks (`,` or `;` then a space),
/// then, for pieces still too long, at word boundaries.
fn split_long(text: &str, span: Span, count: &dyn Fn(&str) -> usize, hard_cap: usize) -> Vec<Span> {
    let s = &text[span.start..span.end];
    if count(s) <= hard_cap {
        return vec![span];
    }
    // clause pieces
    let mut parts: Vec<Span> = Vec::new();
    let mut piece_start = span.start;
    let chars: Vec<(usize, char)> = s.char_indices().collect();
    let mut k = 0;
    while k < chars.len() {
        let (off, c) = chars[k];
        if (c == ',' || c == ';') && k + 1 < chars.len() && chars[k + 1].1 == ' ' {
            parts.push(Span { start: piece_start, end: span.start + off + 1 });
            piece_start = span.start + chars[k + 1].0 + 1;
        }
        k += 1;
    }
    if piece_start < span.end {
        parts.push(Span { start: piece_start, end: span.end });
    }
    // pack clause pieces up to the cap
    let mut packed: Vec<Span> = Vec::new();
    let mut cur: Option<Span> = None;
    for p in parts {
        match cur {
            Some(c) if count(&text[c.start..p.end]) > hard_cap => {
                packed.push(c);
                cur = Some(p);
            }
            Some(c) => cur = Some(Span { start: c.start, end: p.end }),
            None => cur = Some(p),
        }
    }
    if let Some(c) = cur {
        packed.push(c);
    }
    // word-split anything still over the cap
    let mut out = Vec::new();
    for p in packed {
        if count(&text[p.start..p.end]) <= hard_cap {
            out.push(p);
            continue;
        }
        let mut cur: Option<Span> = None;
        let mut word_start = None;
        let seg = &text[p.start..p.end];
        let mut words: Vec<Span> = Vec::new();
        for (off, ch) in seg.char_indices() {
            if ch == ' ' {
                if let Some(ws) = word_start.take() {
                    words.push(Span { start: p.start + ws, end: p.start + off });
                }
            } else if word_start.is_none() {
                word_start = Some(off);
            }
        }
        if let Some(ws) = word_start {
            words.push(Span { start: p.start + ws, end: p.end });
        }
        for w in words {
            match cur {
                Some(c) if count(&text[c.start..w.end]) > hard_cap => {
                    out.push(c);
                    cur = Some(w);
                }
                Some(c) => cur = Some(Span { start: c.start, end: w.end }),
                None => cur = Some(w),
            }
        }
        if let Some(c) = cur {
            out.push(c);
        }
    }
    out
}

/// Packs whole sentences into chunks of about `target` tokens (never beyond
/// `hard_cap`), carrying the last sentence of a chunk into the next when it is
/// under half the target. `text` must already be [`normalize`]d.
pub fn chunk_spans(text: &str, count: &dyn Fn(&str) -> usize, target: usize, hard_cap: usize) -> Vec<Span> {
    let mut sentences: Vec<Span> = Vec::new();
    for s in split_sentences(text) {
        sentences.extend(split_long(text, s, count, hard_cap));
    }
    let mut chunks: Vec<Span> = Vec::new();
    let mut cur: Vec<Span> = Vec::new();
    let mut n = 0usize;
    for s in sentences {
        let k = count(&text[s.start..s.end]);
        if !cur.is_empty() && n + k > target {
            chunks.push(Span { start: cur[0].start, end: cur[cur.len() - 1].end });
            let last = *cur.last().unwrap();
            let last_k = count(&text[last.start..last.end]);
            if last_k < target / 2 {
                cur = vec![last];
                n = last_k;
            } else {
                cur = Vec::new();
                n = 0;
            }
        }
        cur.push(s);
        n += k;
    }
    if !cur.is_empty() {
        chunks.push(Span { start: cur[0].start, end: cur[cur.len() - 1].end });
    }
    chunks
}

/// The text prepared for matching: normalised, chunked, with token counts.
#[derive(Debug, Clone)]
pub struct Prepared {
    pub text: String,
    pub chunks: Vec<PreparedChunk>,
    pub total_tokens: usize,
    /// Key phrases of the text (see [`phrases`]), capped at [`MAX_PHRASES`].
    pub phrases: Vec<String>,
    /// Byte offset in `text` where the model's own window (256 word pieces)
    /// would have stopped reading; `None` when the whole text fits.
    pub truncation_at: Option<usize>,
}

#[derive(Debug, Clone, Copy)]
pub struct PreparedChunk {
    pub span: Span,
    pub tokens: usize,
}

impl Prepared {
    /// How a plain (unchunked) search would have treated this chunk:
    /// `read`, `partial` (it straddles the cutoff) or `unread`.
    pub fn window_of(&self, chunk: &PreparedChunk) -> &'static str {
        match self.truncation_at {
            None => "read",
            Some(cut) if chunk.span.end <= cut => "read",
            Some(cut) if chunk.span.start >= cut => "unread",
            Some(_) => "partial",
        }
    }
}


// ----------------------------------------------------------- key phrases

use std::sync::LazyLock;

static SPLIT: LazyLock<regex::Regex> = LazyLock::new(|| {
    regex::Regex::new(r"(?i)\s*(?:[;,:()\x{2014}]|\band\b|\bincluding\b|\bsuch as\b|\bvia\b|\bwith\b|\bthrough\b|\bacross\b)\s*").unwrap()
});
static FILLER: LazyLock<regex::Regex> = LazyLock::new(|| {
    regex::Regex::new(r"(?i)^(specializing in|focused on|focus on|such as|including|operates across|operates in|offers|provides|provide|delivers|develops|manufactures|makes|sells|engaged in|active in|known for)\s+").unwrap()
});
static AMP: LazyLock<regex::Regex> = LazyLock::new(|| regex::Regex::new(r"\s*&\s*").unwrap());
static DIGIT_TOKEN: LazyLock<regex::Regex> = LazyLock::new(|| regex::Regex::new(r"\b\S*\d\S*\b").unwrap());
static WORD: LazyLock<regex::Regex> = LazyLock::new(|| regex::Regex::new(r"[A-Za-z][A-Za-z\-]+").unwrap());
const STOP: &[&str] = &[
    "the", "a", "an", "of", "in", "on", "to", "for", "by", "as", "is", "are", "was", "were", "has", "have", "its", "their", "our",
    "company", "companies", "group", "global", "major", "leading", "several", "key", "world", "worldwide",
];
const NONBIZ: &[&str] = &[
    "founded", "headquartered", "headquarters", "employees", "workforce", "committed", "achieving", "neutrality", "evolved",
    "nearly", "globally", "innovation", "transformation", "operates",
];

/// Short business phrases from normalised text: fragments of 2-7 words with at
/// least two content words ("data storage", "power grids", "advanced railway
/// mobility"). A phrase matches a short code title far better than the paragraph
/// around it, so each is also queried on its own. Mirrors `chunker.phrases`.
pub fn phrases(text: &str) -> Vec<String> {
    // "&" means "and"; a token containing a digit ("60th", "2030", "290,000") is a break
    // point, not text to be stripped of its digits (mirrors chunker.phrases)
    let text = AMP.replace_all(text, " and ");
    let text = normalize(&DIGIT_TOKEN.replace_all(&text, ","));
    let mut out: Vec<String> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for s in split_sentences(&text) {
        for frag in SPLIT.split(&text[s.start..s.end]) {
            let frag = FILLER.replace(frag.trim(), "");
            let words: Vec<&str> = WORD.find_iter(&frag).map(|m| m.as_str()).collect();
            if words.iter().any(|w| NONBIZ.contains(&w.to_lowercase().as_str())) {
                continue;
            }
            let content = words.iter().filter(|w| !STOP.contains(&w.to_lowercase().as_str())).count();
            if (2..=7).contains(&words.len()) && content >= 2 {
                let joined = words.join(" ");
                if seen.insert(joined.to_lowercase()) {
                    out.push(joined);
                }
            }
        }
    }
    out
}

// --------------------------------------------------------- search + choose

/// One corpus entry as one chunk saw it.
#[derive(Debug, Clone)]
pub struct ChunkHit {
    pub system: String,
    pub unique_key: String,
    pub levels: Vec<Level>,
    pub similarity: f32,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct Level {
    pub level: &'static str,
    pub id: String,
    pub description: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct Entry {
    pub unique_key: String,
    /// The class-level code (the last level of `hierarchy`).
    pub code: String,
    pub title: String,
    pub hierarchy: Vec<Level>,
    /// Best similarity over all chunks.
    pub similarity: f32,
    /// How many chunks nominated this entry as one of their best.
    pub votes: usize,
    /// The chunk that scored this entry highest (index into `chunks`).
    pub evidence_chunk: usize,
    /// Set when a key phrase scored it higher than any chunk did.
    pub evidence_phrase: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SystemResult {
    pub system: String,
    pub recommended: Vec<Entry>,
    pub alternatives: Vec<Entry>,
}

struct Agg {
    levels: Vec<Level>,
    best: f32,
    best_chunk: usize,
    best_phrase: Option<String>,
    votes: usize,
    /// Sum of the similarities of the nominations: what ranks the codes, so a
    /// weak nomination cannot outvote a strong one just by being repeated.
    weight: f32,
}

/// `per_chunk[i]` is chunk i's hits for every system, best first within each
/// system. Pure: no I/O, so it is unit-tested with hand-made hits.
/// `per_phrase` carries each key phrase with its hits, same shape as a chunk's.
pub fn choose(per_chunk: &[Vec<ChunkHit>], per_phrase: &[(String, Vec<ChunkHit>)]) -> Vec<SystemResult> {
    let mut systems: Vec<String> = Vec::new();
    for hits in per_chunk.iter().chain(per_phrase.iter().map(|(_, h)| h)) {
        for h in hits {
            if !systems.contains(&h.system) {
                systems.push(h.system.clone());
            }
        }
    }
    let nominees = nominees_per_chunk(per_chunk.len());
    let mut results = Vec::new();
    for system in systems {
        let mut agg: HashMap<String, Agg> = HashMap::new();
        for (ci, hits) in per_chunk.iter().enumerate() {
            for (rank, h) in hits.iter().filter(|h| h.system == system).enumerate() {
                let a = agg.entry(h.unique_key.clone()).or_insert(Agg {
                    levels: h.levels.clone(),
                    best: f32::MIN,
                    best_chunk: ci,
                    best_phrase: None,
                    votes: 0,
                    weight: 0.0,
                });
                if h.similarity > a.best {
                    a.best = h.similarity;
                    a.best_chunk = ci;
                    a.best_phrase = None;
                }
                if rank < nominees {
                    a.votes += 1;
                    a.weight += h.similarity;
                }
            }
        }
        // each key phrase nominates its single best code, when it is a close enough match
        for (text, hits) in per_phrase {
            if let Some(h) = hits.iter().find(|h| h.system == system) {
                if h.similarity >= PHRASE_MIN {
                    let a = agg.entry(h.unique_key.clone()).or_insert(Agg {
                        levels: h.levels.clone(),
                        best: f32::MIN,
                        best_chunk: 0,
                        best_phrase: None,
                        votes: 0,
                        weight: 0.0,
                    });
                    a.votes += 1;
                    a.weight += h.similarity;
                    if h.similarity > a.best {
                        a.best = h.similarity;
                        a.best_phrase = Some(text.clone());
                    }
                }
            }
        }
        let mut ordered: Vec<(&String, &Agg)> = agg.iter().collect();
        ordered.sort_by(|a, b| {
            b.1.weight
                .partial_cmp(&a.1.weight)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(b.1.best.partial_cmp(&a.1.best).unwrap_or(std::cmp::Ordering::Equal))
                .then(a.0.cmp(b.0))
        });
        let to_entry = |(key, a): (&String, &Agg)| Entry {
            unique_key: key.clone(),
            code: a.levels.last().map(|l| l.id.clone()).unwrap_or_default(),
            title: a.levels.last().map(|l| l.description.clone()).unwrap_or_default(),
            hierarchy: a.levels.clone(),
            similarity: a.best,
            votes: a.votes,
            evidence_chunk: a.best_chunk,
            evidence_phrase: a.best_phrase.clone(),
        };
        let mut recommended: Vec<Entry> = ordered
            .iter()
            .filter(|(_, a)| a.votes > 0)
            .take(MAX_RECOMMENDED)
            .map(|x| to_entry(*x))
            .collect();
        // pad to the floor from the best-scoring entries not already chosen
        if recommended.len() < MIN_RECOMMENDED {
            let mut by_sim: Vec<(&String, &Agg)> = agg.iter().collect();
            by_sim.sort_by(|a, b| {
                b.1.best.partial_cmp(&a.1.best).unwrap_or(std::cmp::Ordering::Equal).then(a.0.cmp(b.0))
            });
            for x in by_sim {
                if recommended.len() >= MIN_RECOMMENDED {
                    break;
                }
                if !recommended.iter().any(|e| &e.unique_key == x.0) {
                    recommended.push(to_entry(x));
                }
            }
        }
        let alternatives: Vec<Entry> = ordered
            .iter()
            .filter(|(k, _)| !recommended.iter().any(|e| &e.unique_key == *k))
            .take(ALTERNATIVES)
            .map(|x| to_entry(*x))
            .collect();
        results.push(SystemResult { system, recommended, alternatives });
    }
    results
}

impl super::SicCatalog {
    /// For one query vector: every registered system's `POOL_PER_SYSTEM`
    /// nearest entries (per system, not globally, so a system whose
    /// similarities run lower than another's is not crowded out), best first
    /// within each system, with the full hierarchy.
    pub async fn search_per_system(&self, model_id: &str, query_vector: &[f32]) -> anyhow::Result<Vec<ChunkHit>> {
        self.search_systems(model_id, query_vector, None, None, POOL_PER_SYSTEM).await
    }

    /// The general form: only the systems in `labels` (all when `None`), only
    /// the classes in `codes` (all when `None`), `limit` nearest per system.
    pub async fn search_systems(
        &self,
        model_id: &str,
        query_vector: &[f32],
        labels: Option<&[String]>,
        codes: Option<&[String]>,
        limit: usize,
    ) -> anyhow::Result<Vec<ChunkHit>> {
        let info = model_info(model_id).ok_or_else(|| anyhow::anyhow!("unknown model id: {model_id}"))?;
        if query_vector.len() != info.dim {
            anyhow::bail!("query vector dim {} does not match model dim {}", query_vector.len(), info.dim);
        }
        let literal = format_float_array_literal(query_vector);
        let filter = match codes {
            Some([]) => return Ok(Vec::new()),
            Some(c) => format!(
                " WHERE class_id IN ({})",
                c.iter().map(|x| format!("'{}'", x.replace('\'', "''"))).collect::<Vec<_>>().join(", ")
            ),
            None => String::new(),
        };
        let per_system: Vec<String> = self
            .systems
            .iter()
            .filter(|system| labels.is_none_or(|l| l.iter().any(|x| x == &system.source_label)))
            .map(|system| {
                let label = system.source_label.replace('\'', "''");
                format!(
                    "(SELECT arrow_cast('{label}', 'LargeUtf8') AS source_type, unique_key, \
                     section_id, section_desc, division_id, division_desc, group_id, group_desc, \
                     class_id, class_desc, \
                     array_distance({col}, arrow_cast({literal}, 'FixedSizeList({dim}, Float32)')) AS distance \
                     FROM {table}{filter} ORDER BY distance ASC LIMIT {limit})",
                    col = info.vector_column,
                    dim = info.dim,
                    table = system.table_name,
                )
            })
            .collect();
        if per_system.is_empty() {
            return Ok(Vec::new());
        }
        let sql = per_system.join(" UNION ALL ");
        let batches = self.ctx.sql(&sql).await?.collect().await?;

        let mut hits: Vec<ChunkHit> = Vec::new();
        for batch in &batches {
            let s = |name: &str| -> &LargeStringArray {
                batch
                    .column_by_name(name)
                    .unwrap_or_else(|| panic!("missing column {name}"))
                    .as_any()
                    .downcast_ref::<LargeStringArray>()
                    .unwrap_or_else(|| panic!("column {name} is not LargeStringArray"))
            };
            let (src, key) = (s("source_type"), s("unique_key"));
            let (sec_id, sec_d) = (s("section_id"), s("section_desc"));
            let (div_id, div_d) = (s("division_id"), s("division_desc"));
            let (grp_id, grp_d) = (s("group_id"), s("group_desc"));
            let (cls_id, cls_d) = (s("class_id"), s("class_desc"));
            let dist = batch.column_by_name("distance").unwrap();
            for i in 0..batch.num_rows() {
                let d: f32 = if let Some(a) = dist.as_any().downcast_ref::<Float32Array>() {
                    a.value(i)
                } else if let Some(a) = dist.as_any().downcast_ref::<Float64Array>() {
                    a.value(i) as f32
                } else {
                    anyhow::bail!("distance column is neither Float32 nor Float64");
                };
                hits.push(ChunkHit {
                    system: src.value(i).to_string(),
                    unique_key: key.value(i).to_string(),
                    levels: vec![
                        Level { level: "section", id: sec_id.value(i).into(), description: sec_d.value(i).into() },
                        Level { level: "division", id: div_id.value(i).into(), description: div_d.value(i).into() },
                        Level { level: "group", id: grp_id.value(i).into(), description: grp_d.value(i).into() },
                        Level { level: "class", id: cls_id.value(i).into(), description: cls_d.value(i).into() },
                    ],
                    similarity: 1.0 - (d * d) / 2.0,
                });
            }
        }
        // best first within each system (the UNION does not guarantee order)
        hits.sort_by(|a, b| {
            a.system.cmp(&b.system).then(b.similarity.partial_cmp(&a.similarity).unwrap_or(std::cmp::Ordering::Equal))
        });
        Ok(hits)
    }
}

// ------------------------------------------------------------------ tests

#[cfg(test)]
mod tests {
    use super::*;

    fn words(s: &str) -> usize {
        s.split_whitespace().count()
    }

    fn texts(text: &str, spans: &[Span]) -> Vec<String> {
        spans.iter().map(|s| text[s.start..s.end].to_string()).collect()
    }

    #[test]
    fn abbreviations_do_not_split() {
        let t = normalize("Apple Inc. is an American company. It was founded by Steve Jobs in the U.S. in 1976. J. Smith runs it.");
        assert_eq!(split_sentences(&t).len(), 3);
    }

    #[test]
    fn short_text_is_one_chunk() {
        let t = normalize("One sentence only.");
        assert_eq!(texts(&t, &chunk_spans(&t, &words, 128, 200)), vec!["One sentence only."]);
    }

    #[test]
    fn chunks_stay_under_the_cap_and_cover_everything() {
        let t = normalize(
            &(0..40).map(|i| format!("Sentence number {i} talks about thing {i} at some length here.")).collect::<Vec<_>>().join(" "),
        );
        let cs = chunk_spans(&t, &words, 30, 50);
        assert!(cs.len() > 3);
        let ts = texts(&t, &cs);
        assert!(ts.iter().all(|c| words(c) <= 50));
        let joined = ts.join(" ");
        for i in 0..40 {
            assert!(joined.contains(&format!("Sentence number {i} ")));
        }
    }

    #[test]
    fn one_sentence_overlap() {
        let t = normalize("Aa bb. Cc dd. Ee ff. Gg hh. Ii jj. Kk ll.");
        let ts = texts(&t, &chunk_spans(&t, &words, 6, 10));
        assert_eq!(ts[0], "Aa bb. Cc dd. Ee ff.");
        assert!(ts[1].starts_with("Ee ff."));
    }

    #[test]
    fn an_overlong_sentence_is_split() {
        let s = format!("{}.", (0..100).map(|i| format!("word{i}")).collect::<Vec<_>>().join(", "));
        let t = normalize(&s);
        let ts = texts(&t, &chunk_spans(&t, &words, 20, 30));
        assert!(ts.iter().all(|c| words(c) <= 30));
        assert!(ts.len() > 2);
    }

    fn hit(system: &str, key: &str, sim: f32) -> ChunkHit {
        ChunkHit {
            system: system.into(),
            unique_key: key.into(),
            levels: vec![
                Level { level: "division", id: "D".into(), description: "Division".into() },
                Level { level: "class", id: key.into(), description: format!("Class {key}") },
            ],
            similarity: sim,
        }
    }

    #[test]
    fn each_chunk_nominates_so_a_multi_business_company_gets_a_set() {
        // chunk 0 is about hardware (A,B), chunk 1 about services (C,D), chunk 2 hardware again (A)
        let per_chunk = vec![
            vec![hit("X", "A", 0.6), hit("X", "B", 0.5), hit("X", "E", 0.4)],
            vec![hit("X", "C", 0.55), hit("X", "D", 0.5), hit("X", "A", 0.3)],
            vec![hit("X", "A", 0.58), hit("X", "F", 0.45), hit("X", "B", 0.2)],
        ];
        let r = &choose(&per_chunk, &[])[0];
        let keys: Vec<&str> = r.recommended.iter().map(|e| e.unique_key.as_str()).collect();
        // A: 2 votes; B, C, D, F: 1 vote each; ordered by votes then best similarity
        assert_eq!(keys, vec!["A", "C", "B", "D", "F"]);
        assert_eq!(r.recommended[0].votes, 2);
        assert_eq!(r.recommended[0].evidence_chunk, 0);
        assert!(r.alternatives.iter().all(|e| !keys.contains(&e.unique_key.as_str())));
    }

    #[test]
    fn the_set_is_never_smaller_than_two_or_larger_than_five() {
        // a single short paragraph still yields a set: one chunk nominates up to five
        let one: Vec<ChunkHit> = ["A", "B", "C", "D", "E", "F", "G"].iter().enumerate().map(|(i, k)| hit("X", k, 0.6 - i as f32 * 0.05)).collect();
        let r = &choose(&[one], &[])[0];
        assert_eq!(r.recommended.len(), 5);
        assert_eq!(r.alternatives.len(), 2);
        // and with only two candidates at all, exactly two
        let r = &choose(&[vec![hit("X", "A", 0.6), hit("X", "B", 0.5)]], &[])[0];
        assert_eq!(r.recommended.len(), 2);
        // more chunks, fewer nominations each
        assert_eq!(nominees_per_chunk(1), 5);
        assert_eq!(nominees_per_chunk(2), 3);
        assert_eq!(nominees_per_chunk(3), 2);
        assert_eq!(nominees_per_chunk(16), 2);
        // many chunks with different winners: capped at five
        let many: Vec<Vec<ChunkHit>> = (0..9)
            .map(|i| vec![hit("X", &format!("K{i}"), 0.5), hit("X", &format!("L{i}"), 0.4)])
            .collect();
        assert_eq!(choose(&many, &[])[0].recommended.len(), MAX_RECOMMENDED);
    }

    #[test]
    fn systems_are_answered_independently() {
        let per_chunk = vec![vec![hit("US SIC", "a", 0.6), hit("US SIC", "b", 0.5), hit("ISIC Rev. 4", "z", 0.4), hit("ISIC Rev. 4", "y", 0.3)]];
        let r = choose(&per_chunk, &[]);
        assert_eq!(r.len(), 2);
        assert_eq!(r[0].system, "US SIC");
        assert_eq!(r[1].system, "ISIC Rev. 4");
        assert_eq!(r[1].recommended[0].unique_key, "z");
    }

    const HITACHI: &str = "Hitachi, Ltd. is a major Japanese multinational conglomerate headquartered in Tokyo, specializing in digital solutions, green energy, and sustainable infrastructure. Founded in 1910 as an electrical repair shop, the company has evolved into a global powerhouse combining information technology (IT) with operational technology (OT) to drive social innovation. Hitachi operates across several key sectors, including digital services (such as data storage via Hitachi Vantara), power grids and clean energy solutions (Hitachi Energy), advanced railway mobility, and industrial systems. With a workforce of nearly 290,000 employees globally, the company is highly focused on digital transformation and has committed to achieving carbon neutrality across its operations by 2030.";

    #[test]
    fn a_marketing_list_becomes_business_phrases() {
        let p = phrases(&normalize(HITACHI));
        for want in [
            "digital solutions", "green energy", "sustainable infrastructure", "data storage", "power grids",
            "clean energy solutions", "advanced railway mobility", "industrial systems",
        ] {
            assert!(p.contains(&want.to_string()), "missing {want:?} in {p:?}");
        }
        for junk in ["workforce of nearly", "employees globally", "Hitachi operates"] {
            assert!(!p.contains(&junk.to_string()), "{junk:?} should not be a phrase: {p:?}");
        }
        // the exact list the Python spec produces (chunker.py)
        assert_eq!(p.len(), 13, "{p:?}");
        assert!(phrases("Big. Old.").is_empty());
    }

    #[test]
    fn a_phrase_nominates_its_best_code_only_when_close_enough() {
        // the chunks point at junk X, Y; the phrase "power grids" points at P strongly, "social thing" only weakly at W
        let chunks = vec![vec![hit("S", "X", 0.30), hit("S", "Y", 0.28)]];
        let phrases_hits = vec![
            ("power grids".to_string(), vec![hit("S", "P", 0.55), hit("S", "X", 0.20)]),
            ("social thing".to_string(), vec![hit("S", "W", 0.31)]),
        ];
        let r = &choose(&chunks, &phrases_hits)[0];
        let keys: Vec<&str> = r.recommended.iter().map(|e| e.unique_key.as_str()).collect();
        assert!(keys.contains(&"P"), "{keys:?}");
        assert!(!keys.contains(&"W"), "a weak phrase match must not nominate: {keys:?}");
        let p = r.recommended.iter().find(|e| e.unique_key == "P").unwrap();
        assert_eq!(p.evidence_phrase.as_deref(), Some("power grids"));
        // a code the chunks scored higher keeps the chunk as its evidence
        let x = r.recommended.iter().find(|e| e.unique_key == "X").unwrap();
        assert_eq!(x.evidence_phrase, None);
    }

    #[test]
    fn ampersands_and_digit_tokens() {
        let p = phrases(&normalize("Its divisions include Fabric & Home Care, and it is ranked 60th on the Forbes Global 2000 list."));
        assert!(p.contains(&"Home Care".to_string()), "{p:?}");
        assert!(!p.iter().any(|x| x.contains("th on") || x.contains("2000")), "{p:?}");
    }
}
