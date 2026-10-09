//! Rebuilds `lib/edgar.py`'s `get_firmographics()` output shape from
//! `edgarkit`'s `Submission` - promoted from
//! `experiments/edgar-spike/`'s `firmographics_test`, which validated
//! this against real IBM data with no `pyedgar` and no hand-rolled JSON
//! parsing needed.
//!
//! Deliberately EDGAR-only: `get_firmographics()`'s SIC cross-reference
//! (division/majorGroup/industryGroup, via `lib/sic.py` against local
//! SIC data) is a separate system - `company-dns-sic`'s job, not this
//! crate's. The `sicDescription` field below is the raw SEC value;
//! callers combining EDGAR + SIC data overwrite it, the way
//! `lib/edgar.py` itself does.

use edgarkit::Submission;

const UKN: &str = "Unknown";

fn or_unknown(v: &Option<String>) -> String {
    match v {
        Some(s) if !s.is_empty() => s.clone(),
        _ => UKN.to_string(),
    }
}

/// Builds the `get_firmographics()`-equivalent JSON shape from a real
/// `edgarkit::Submission`. Note on a real bug found while validating
/// this in `experiments/edgar-spike/`: `lib/edgar.py`'s current
/// "cleanup stock information" step overwrites `tickers` with
/// `[exchange, ticker]` instead of the real ticker list - this function
/// intentionally does *not* replicate that, returning the actual
/// `tickers`/`exchanges` lists instead.
pub fn build_firmographics(submission: &Submission) -> serde_json::Value {
    let my_cik = submission.cik.trim_start_matches('0');
    let cik_padded = &submission.cik;

    let firmographics_url = format!("https://data.sec.gov/submissions/CIK{cik_padded}.json");
    let company_facts_url =
        format!("https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json");
    let filings_url =
        format!("https://www.sec.gov/cgi-bin/browse-edgar?CIK={my_cik}&action=getcompany");
    let transactions_by_issuer =
        format!("https://www.sec.gov/cgi-bin/own-disp?action=getissuer&CIK={my_cik}");
    let transactions_by_owner =
        format!("https://www.sec.gov/cgi-bin/own-disp?action=getowner&CIK={my_cik}");

    let mailing = &submission.addresses.mailing;
    let address = match &mailing.street2 {
        Some(s2) if !s2.is_empty() => format!("{} {}", mailing.street1, s2),
        _ => mailing.street1.clone(),
    };

    serde_json::json!({
        "name": submission.name,
        "cik": submission.cik,
        "sic": submission.sic,
        "sicDescription": submission.sic_description,
        "tickers": submission.tickers,
        "exchanges": submission.exchanges,
        "ein": or_unknown(&submission.ein),
        "description": or_unknown(&submission.description),
        "website": or_unknown(&submission.website),
        "category": or_unknown(&submission.category),
        "fiscalYearEnd": or_unknown(&submission.fiscal_year_end),
        "stateOfIncorporation": submission.state_of_incorporation,
        "phone": submission.phone,
        "entityType": submission.entity_type,
        "companyFactsURL": company_facts_url,
        "firmographicsURL": firmographics_url,
        "filingsURL": filings_url,
        "transactionsByIssuer": transactions_by_issuer,
        "transactionsByOwner": transactions_by_owner,
        "city": mailing.city,
        "stateProvince": mailing.state_or_country,
        "zipPostal": mailing.zip_code,
        "address": address,
    })
}
