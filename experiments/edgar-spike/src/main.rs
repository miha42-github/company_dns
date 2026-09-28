// Disposable spike for docs/plans/edgar-backend.md - not part of the
// rewrite, not committed as production code. Tests edgarkit's `company`
// and `index` features against real SEC EDGAR data, to check whether it
// can replace the two things the current Python implementation does:
// lib/edgar.py's get_firmographics() (live JSON REST call, no pyedgar)
// and lib/prepare_edgar_data.py's ExtractEdgarData (pyedgar's
// IndexMaker, quarterly full-text index -> filtered `10-%` companies
// table). See edgar-backend.md sec2.1/sec5 for what this is meant to answer.

use edgarkit::{CompanyOperations, Edgar, EdgarPeriod, FilingOperations, IndexOperations, Quarter};

const USER_AGENT: &str = "Mediumroast, Inc. edgar-spike hello@mediumroast.io";

// IBM - a real, stable CIK already used as the running example
// elsewhere in this doc set (ic-similarity-search-poc.md's truncation
// discussion, go-duckdb-rewrite.md's firmographics URL example).
const IBM_CIK: &str = "0000051143";

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let edgar = Edgar::new(USER_AGENT)?;

    company_test(&edgar).await?;
    index_test(&edgar).await?;

    Ok(())
}

/// Does edgarkit's `company`/`filings` feature cover what
/// get_firmographics() needs, without pyedgar or hand-rolled JSON
/// parsing?
async fn company_test(edgar: &Edgar) -> Result<(), Box<dyn std::error::Error>> {
    println!("=== Company test: submissions({}) (IBM) ===", IBM_CIK);

    let submission = edgar.submissions(IBM_CIK).await?;

    println!("name:                  {}", submission.name);
    println!("cik:                   {}", submission.cik);
    println!("sic:                   {}", submission.sic);
    println!("sic_description:       {}", submission.sic_description);
    println!("tickers:               {:?}", submission.tickers);
    println!("exchanges:             {:?}", submission.exchanges);
    println!("ein:                   {:?}", submission.ein);
    println!("description:           {:?}", submission.description);
    println!("website:               {:?}", submission.website);
    println!("category:              {:?}", submission.category);
    println!("fiscal_year_end:       {:?}", submission.fiscal_year_end);
    println!(
        "state_of_incorporation: {}",
        submission.state_of_incorporation
    );
    println!("phone:                 {}", submission.phone);
    println!("addresses:             {:?}", submission.addresses);

    let facts = edgar.company_facts(51143).await;
    match facts {
        Ok(_) => println!("company_facts(51143):  ok"),
        Err(e) => println!("company_facts(51143):  ERROR: {e}"),
    }

    println!();
    Ok(())
}

/// Does edgarkit's `index` feature cover what pyedgar's IndexMaker does
/// - download + parse a real quarterly full-text index, then filter to
/// the same '10-%' form-type family lib/prepare_edgar_data.py keeps?
async fn index_test(edgar: &Edgar) -> Result<(), Box<dyn std::error::Error>> {
    // A recent, fully-published quarter as of this spike (2026-09-28).
    let period = EdgarPeriod::new(2025, Quarter::Q2)?;
    println!(
        "=== Index test: get_period_filings({}, Q{:?}) ===",
        period.year(),
        period.quarter()
    );

    let started = std::time::Instant::now();
    let entries = edgar.get_period_filings(period, None).await?;
    let elapsed = started.elapsed();

    let total = entries.len();
    let ten_series: Vec<_> = entries
        .iter()
        .filter(|e| e.form_type.starts_with("10-"))
        .collect();

    println!("total entries:         {total}");
    println!("'10-%' entries:        {}", ten_series.len());
    println!(
        "'10-%' as % of total:  {:.2}%",
        100.0 * ten_series.len() as f64 / total.max(1) as f64
    );
    println!("download+parse time:   {elapsed:?}");

    if let Some(first) = ten_series.first() {
        println!("sample entry:          {first:?}");
    }

    println!();
    accession_and_date_test(&ten_series).await?;

    Ok(())
}

/// lib/edgar.py needs two things IndexEntry doesn't hand over directly:
/// the accession number (to build filing_idx/filing_idx_url, e.g.
/// EDGARARCHIVES/{cik}/{accession_no_dashes}/{accession}-index.html)
/// and year/month/day split out of date_filed (ACCESSION/YEAR/MONTH/DAY
/// in lib/edgar.py's SQL row tuple). Checks whether both are cheaply
/// derivable from what IndexEntry actually gives us, then verifies the
/// derived filing-index URL against a small sample by fetching it for
/// real - not just eyeballing that it looks right.
async fn accession_and_date_test(
    ten_series: &[&edgarkit::parsing::index::IndexEntry],
) -> Result<(), Box<dyn std::error::Error>> {
    println!("=== Deriving accession-number + date parts from IndexEntry ===");

    let http = reqwest::Client::builder().build()?;

    let mut checked = 0;
    let mut ok = 0;

    for entry in ten_series.iter().take(5) {
        let accession = match extract_accession(&entry.url) {
            Some(a) => a,
            None => {
                println!("  {} -> could not extract accession from url", entry.url);
                continue;
            }
        };
        let accession_no_dashes = accession.replace('-', "");

        let date_parts = match split_date_filed(&entry.date_filed) {
            Some(parts) => parts,
            None => {
                println!(
                    "  {} -> could not split date_filed {:?}",
                    entry.company_name, entry.date_filed
                );
                continue;
            }
        };

        // Same construction as lib/edgar.py's filing_idx_url.
        let filing_idx_url = format!(
            "https://www.sec.gov/Archives/edgar/data/{}/{}/{}-index.html",
            entry.cik, accession_no_dashes, accession
        );

        checked += 1;
        let resp = http
            .head(&filing_idx_url)
            .header("User-Agent", USER_AGENT)
            .send()
            .await;

        match resp {
            Ok(r) if r.status().is_success() => {
                ok += 1;
                println!(
                    "  {} | accession {} | filed {}-{:02}-{:02} | index URL 200 OK",
                    entry.company_name, accession, date_parts.0, date_parts.1, date_parts.2
                );
            }
            Ok(r) => println!(
                "  {} | accession {} | index URL -> HTTP {}",
                entry.company_name,
                accession,
                r.status()
            ),
            Err(e) => println!(
                "  {} | accession {} | index URL request failed: {e}",
                entry.company_name, accession
            ),
        }
    }

    println!("verified {ok}/{checked} derived filing-index URLs resolve (HTTP 200)");
    println!();
    Ok(())
}

/// IndexEntry.url looks like:
/// https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt
/// - the accession number is the filename, dashes and all.
fn extract_accession(url: &str) -> Option<String> {
    let file_name = url.rsplit('/').next()?;
    file_name.strip_suffix(".txt").map(str::to_string)
}

/// date_filed is "YYYY-MM-DD" - trivial to split, not pre-parsed.
fn split_date_filed(date_filed: &str) -> Option<(i32, u32, u32)> {
    let mut parts = date_filed.splitn(3, '-');
    let y = parts.next()?.parse().ok()?;
    let m = parts.next()?.parse().ok()?;
    let d = parts.next()?.parse().ok()?;
    Some((y, m, d))
}
