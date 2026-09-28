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

use serde_json::json;

/// Builds the merged-firmographics response. `edgar` is the result of
/// an EDGAR catalog name search + firmographics fetch, if any matched.
/// `wikipedia` is `Ok(data)` on a real successful lookup or
/// `Err(message)` on a genuine miss/failure (§8.1's `WikipediaError`
/// stringified) - not an `Option`, since "no Wikipedia data" always has
/// a reason worth surfacing (V3-parity: `Err` carries the same hint
/// text `lib/wikipedia_v2.py`'s `lookup_error` computes).
pub fn merge(
    company_name: &str,
    edgar: Option<serde_json::Value>,
    wikipedia: Result<serde_json::Value, String>,
) -> serde_json::Value {
    match (edgar, wikipedia) {
        (Some(edgar_data), Ok(wiki_data)) => json!({
            "query": company_name,
            "source": "edgar+wikipedia",
            "edgar": edgar_data,
            "wikipedia": wiki_data,
        }),
        (Some(edgar_data), Err(wiki_err)) => json!({
            "query": company_name,
            "source": "edgar-only",
            "note": format!("Wikipedia data unavailable ({wiki_err})."),
            "edgar": edgar_data,
        }),
        (None, Ok(wiki_data)) => json!({
            "query": company_name,
            "source": "wikipedia-only",
            "note": "No EDGAR catalog match for this name.",
            "wikipedia": wiki_data,
        }),
        (None, Err(wiki_err)) => json!({
            "query": company_name,
            "source": "none",
            "note": format!("No EDGAR match and Wikipedia data unavailable ({wiki_err})."),
        }),
    }
}
