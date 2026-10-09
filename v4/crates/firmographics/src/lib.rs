//! Mirrors `lib/firmographics.py`'s `GeneralQueriesV2.get_firmographics`
//! shape (Wikipedia-first, EDGAR merged in when available). Real EDGAR
//! and real Wikipedia (§8.1, built 2026-09-28 - `company-dns-wikipedia`
//! is no longer a stub) are both wired in now; this crate's own job is
//! just combining whatever each side returned into one response, same
//! as `lib/firmographics.py` does. The endpoint routes correctly
//! (`GET /V4.0/global/company/merged/firmographics/{company_name}`,
//! V3's own shape).
//!
//! **Fixed (2026-09-28), found while verifying the wikipedia promotion
//! live**: `merge` previously took `wikipedia_error: Option<String>`
//! only - no parameter existed for successful Wikipedia data at all,
//! a leftover from when §8.1 was a stub that always errored. Once §8.1
//! started actually succeeding, this bug became real and visible: a
//! successful merge claimed `"source": "edgar+wikipedia"` while
//! silently omitting the Wikipedia data from the response entirely.
//! Now takes `wikipedia: Result<Value, String>` and actually includes
//! the data on success.
//!
//! **Fixed (2026-10-04): the EDGAR side is matched by CIK, not by name
//! substring.** V3's `merge_data` takes the CIK out of the Wikipedia
//! record and asks EDGAR for exactly that company. V4 had been running
//! `ILIKE '%name%'` over the catalog instead, which merged unrelated
//! companies in ("Apple" -> "PINEAPPLE EXPRESS CANNABIS Co") and missed
//! ones whose EDGAR name differs from the query ("IBM" -> "INTERNATIONAL
//! BUSINESS MACHINES CORP"). The helpers below ([`cik_from_wikipedia`],
//! [`name_matches`]) are what the endpoint now uses; see
//! `docs/plans/v4-server-prototype.md` §8.2.

use serde_json::{json, Value};

/// How the EDGAR side of a merge was found, and why it is missing when it
/// is. Built by the caller (`main.rs`) from the catalog lookups it ran.
#[derive(Debug, Clone, Default)]
pub struct EdgarLookup {
    /// `Some("cik")` when matched through the CIK Wikipedia reported,
    /// `Some("name")` when matched by a careful company-name match,
    /// `None` when there is no EDGAR data.
    pub matched_by: Option<&'static str>,
    /// The CIK Wikipedia reported for the company, if it reported a usable one.
    pub wiki_cik: Option<u64>,
    /// Name fallback only: how many distinct EDGAR companies matched the name
    /// (more than one means the name alone cannot say which is meant).
    pub ambiguous_companies: usize,
    /// False when no EDGAR catalog is loaded at all.
    pub catalog_loaded: bool,
}

/// Builds the merged-firmographics response. `edgar` is the EDGAR catalog
/// rows for the matched company, if any. `wikipedia` is `Ok(data)` on a
/// real successful lookup or `Err(message)` on a genuine miss/failure
/// (§8.1's `WikipediaError` stringified) - not an `Option`, since "no
/// Wikipedia data" always has a reason worth surfacing (V3-parity: `Err`
/// carries the same hint text `lib/wikipedia_v2.py`'s `lookup_error`
/// computes). `lookup` says how the EDGAR side was matched, so a missing
/// EDGAR section is explained rather than guessed at.
pub fn merge(
    company_name: &str,
    edgar: Option<Value>,
    wikipedia: Result<Value, String>,
    lookup: &EdgarLookup,
) -> Value {
    let matched_by = lookup.matched_by.unwrap_or("none");
    match (edgar, wikipedia) {
        (Some(edgar_data), Ok(wiki_data)) => json!({
            "query": company_name,
            "source": "edgar+wikipedia",
            "edgar_match": matched_by,
            "edgar": edgar_data,
            "wikipedia": wiki_data,
        }),
        (Some(edgar_data), Err(wiki_err)) => json!({
            "query": company_name,
            "source": "edgar-only",
            "edgar_match": matched_by,
            "note": format!("Wikipedia data unavailable ({wiki_err})."),
            "edgar": edgar_data,
        }),
        (None, Ok(wiki_data)) => json!({
            "query": company_name,
            "source": "wikipedia-only",
            "note": no_edgar_note(lookup),
            "wikipedia": wiki_data,
        }),
        (None, Err(wiki_err)) => json!({
            "query": company_name,
            "source": "none",
            "note": format!("{} Wikipedia data unavailable ({wiki_err}).", no_edgar_note(lookup)),
        }),
    }
}

fn no_edgar_note(lookup: &EdgarLookup) -> String {
    if !lookup.catalog_loaded {
        "No EDGAR catalog is loaded.".to_string()
    } else if let Some(cik) = lookup.wiki_cik {
        format!("Wikipedia reports CIK {cik}, but the loaded EDGAR catalog has no filings for it.")
    } else if lookup.ambiguous_companies > 1 {
        format!(
            "{} EDGAR companies match this name and Wikipedia gave no CIK to choose between them; use a fuller name or the company's CIK.",
            lookup.ambiguous_companies
        )
    } else {
        "No EDGAR catalog match for this name.".to_string()
    }
}

/// The CIK in a Wikipedia firmographics record, if it is a usable one.
/// Wikipedia reports it as a zero-padded string (`"0000051143"`), as the
/// literal `"Unknown"` when Wikidata has none (e.g. the page "Apple"), or
/// occasionally as a list when several are listed - V3 treats a list the
/// same as unknown, because it cannot say which one is meant.
pub fn cik_from_wikipedia(wiki: &Value) -> Option<u64> {
    let digits = wiki.get("cik")?.as_str()?.trim();
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    digits.parse::<u64>().ok().filter(|cik| *cik > 0)
}

/// Lower-cases and strips punctuation so `"Apple Inc."`, `"APPLE INC"` and
/// `"apple, inc"` compare equal.
fn normalize(name: &str) -> String {
    name.chars()
        .map(|c| if c.is_alphanumeric() { c.to_ascii_lowercase() } else { ' ' })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

/// Whether an EDGAR company name is a plausible match for the name the user
/// typed: equal after normalising, or starting with it at a word boundary
/// (`"apple"` matches `"APPLE INC"` and `"APPLE HOSPITALITY REIT"`, but not
/// `"PINEAPPLE EXPRESS CANNABIS CO"`; `"international business machines"`
/// matches `"INTERNATIONAL BUSINESS MACHINES CORP"`). A substring match in
/// the middle of a word or name is exactly what this exists to refuse.
pub fn name_matches(edgar_company_name: &str, query: &str) -> bool {
    let (name, query) = (normalize(edgar_company_name), normalize(query));
    if query.is_empty() {
        return false;
    }
    name == query || name.starts_with(&format!("{query} "))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cik_is_taken_only_from_a_real_digit_string() {
        assert_eq!(cik_from_wikipedia(&json!({"cik": "0000051143"})), Some(51143));
        assert_eq!(cik_from_wikipedia(&json!({"cik": "320193"})), Some(320193));
        assert_eq!(cik_from_wikipedia(&json!({"cik": "Unknown"})), None);
        assert_eq!(cik_from_wikipedia(&json!({"cik": ""})), None);
        assert_eq!(cik_from_wikipedia(&json!({"cik": "0000000000"})), None);
        // several CIKs listed: ambiguous, treated as unknown (V3 does the same)
        assert_eq!(cik_from_wikipedia(&json!({"cik": ["0000051143", "0000012345"]})), None);
        assert_eq!(cik_from_wikipedia(&json!({"name": "no cik key"})), None);
    }

    #[test]
    fn names_match_whole_leading_words_never_substrings() {
        assert!(name_matches("APPLE INC", "Apple"));
        assert!(name_matches("Apple Inc.", "apple inc"));
        assert!(name_matches("INTERNATIONAL BUSINESS MACHINES CORP", "International Business Machines"));
        assert!(name_matches("Tesla, Inc.", "Tesla"));
        // the reported bug
        assert!(!name_matches("PINEAPPLE EXPRESS CANNABIS Co", "Apple"));
        assert!(!name_matches("CRABAPPLE HOLDINGS", "Apple"));
        // a word in the middle is not a leading match either
        assert!(!name_matches("BIG APPLE BAGELS INC", "Apple"));
        assert!(!name_matches("ANYTHING", ""));
    }

    #[test]
    fn every_source_combination_is_reported_and_missing_edgar_is_explained() {
        let wiki = Ok(json!({"name": "IBM"}));
        let by_cik = EdgarLookup { matched_by: Some("cik"), wiki_cik: Some(51143), catalog_loaded: true, ..Default::default() };
        let m = merge("IBM", Some(json!([{"cik": 51143}])), wiki.clone(), &by_cik);
        assert_eq!((m["source"].as_str(), m["edgar_match"].as_str()), (Some("edgar+wikipedia"), Some("cik")));

        let known_cik = EdgarLookup { wiki_cik: Some(51143), catalog_loaded: true, ..Default::default() };
        let m = merge("IBM", None, wiki.clone(), &known_cik);
        assert_eq!(m["source"], "wikipedia-only");
        assert!(m["note"].as_str().unwrap().contains("CIK 51143"));

        let ambiguous = EdgarLookup { ambiguous_companies: 3, catalog_loaded: true, ..Default::default() };
        assert!(merge("Apple", None, wiki.clone(), &ambiguous)["note"].as_str().unwrap().contains("3 EDGAR companies"));

        let no_catalog = EdgarLookup::default();
        assert_eq!(merge("x", None, wiki, &no_catalog)["note"], "No EDGAR catalog is loaded.");

        let edgar_only = merge("x", Some(json!([])), Err("nope".into()), &by_cik);
        assert_eq!(edgar_only["source"], "edgar-only");
        let none = merge("x", None, Err("nope".into()), &EdgarLookup { catalog_loaded: true, ..Default::default() });
        assert_eq!(none["source"], "none");
    }
}
