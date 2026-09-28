//! Staged, not built (`docs/plans/v4-server-prototype.md` §8.2).
//! Mirrors `lib/firmographics.py`'s `GeneralQueriesV2.get_firmographics`
//! shape (Wikipedia-first, EDGAR merged in when available) - but since
//! `company-dns-wikipedia` (§8.1) is itself a stub, this can only ever
//! produce an EDGAR-only result (when a CIK/catalog match exists) or an
//! explicit not-implemented response, never the real merge. The
//! endpoint routes correctly (`GET /V4.0/global/company/merged/
//! firmographics/{company_name}`, V3's own shape); its response
//! documents the incompleteness rather than silently omitting Wikipedia
//! data.

use serde_json::json;

/// Builds the merged-firmographics response. `edgar` is the result of
/// an EDGAR catalog name search + firmographics fetch, if any matched;
/// `wikipedia_error` is always `Some` today (§8.1's client always
/// returns `NotImplemented`), kept as an `Option` so this function
/// doesn't need to change shape once a real Wikipedia client exists.
pub fn merge(
    company_name: &str,
    edgar: Option<serde_json::Value>,
    wikipedia_error: Option<String>,
) -> serde_json::Value {
    match (edgar, wikipedia_error) {
        (Some(edgar_data), Some(wiki_err)) => json!({
            "query": company_name,
            "source": "edgar-only",
            "note": format!(
                "Wikipedia data unavailable ({wiki_err}) - company-dns-wikipedia \
                 is staged, not implemented yet (v4-server-prototype.md sec8.1). \
                 This is EDGAR data only, not a real merge."
            ),
            "edgar": edgar_data,
        }),
        (None, Some(wiki_err)) => json!({
            "query": company_name,
            "source": "none",
            "note": format!(
                "No EDGAR match and Wikipedia data unavailable ({wiki_err})."
            ),
        }),
        (edgar_data, None) => json!({
            "query": company_name,
            "source": "edgar+wikipedia",
            "edgar": edgar_data,
        }),
    }
}
