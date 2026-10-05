//! The EDGAR "10-x initial catalog" (`docs/plans/v4-server-prototype.md`
//! §4): writing a filtered quarterly index to `.feather`, and querying
//! it back with DataFusion. Promoted from `experiments/edgar-spike/`'s
//! `write_feather` and `experiments/edgar-index-query/`'s read/query
//! side - previously two separate crates because `edgarkit` and
//! DataFusion 42 couldn't share a process; both live here now that the
//! project has moved to DataFusion 55.x (`go-duckdb-rewrite.md` §7.9,
//! `edgar-backend.md` status line).

use datafusion::arrow::array::{Int32Array, StringArray, UInt64Array};
use datafusion::arrow::datatypes::{DataType, Field, Schema};
use datafusion::arrow::ipc::writer::FileWriter;
use datafusion::arrow::record_batch::RecordBatch;
use datafusion::datasource::file_format::options::ArrowReadOptions;
use datafusion::prelude::*;
use edgarkit::{Edgar, EdgarPeriod, IndexOperations};
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;

fn catalog_schema() -> Arc<Schema> {
    Arc::new(Schema::new(vec![
        Field::new("cik", DataType::UInt64, false),
        Field::new("company_name", DataType::Utf8, false),
        Field::new("form_type", DataType::Utf8, false),
        Field::new("year", DataType::Int32, false),
        Field::new("month", DataType::Int32, false),
        Field::new("day", DataType::Int32, false),
        Field::new("accession", DataType::Utf8, false),
        Field::new("url", DataType::Utf8, false),
    ]))
}

/// `IndexEntry.url` looks like
/// `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt` -
/// the accession number is the filename, dashes and all. Verified
/// against 5 real entries in `experiments/edgar-spike/` (5/5 derived
/// filing-index URLs resolved with HTTP 200).
fn extract_accession(url: &str) -> Option<String> {
    let file_name = url.rsplit('/').next()?;
    file_name.strip_suffix(".txt").map(str::to_string)
}

/// `date_filed` is `"YYYY-MM-DD"` - a trivial split, not pre-parsed by
/// `edgarkit`.
fn split_date_filed(date_filed: &str) -> Option<(i32, u32, u32)> {
    let mut parts = date_filed.splitn(3, '-');
    let y = parts.next()?.parse().ok()?;
    let m = parts.next()?.parse().ok()?;
    let d = parts.next()?.parse().ok()?;
    Some((y, m, d))
}

/// One catalog row, before it is written.
#[derive(Debug, Clone)]
pub struct CatalogRow {
    pub cik: u64,
    pub company_name: String,
    pub form_type: String,
    pub year: i32,
    pub month: i32,
    pub day: i32,
    pub accession: String,
    pub url: String,
}

/// Fetches one quarter's filing index via `edgarkit` and keeps the `'10-%'`
/// form family (kept broad - `10-D`, `10-12G`/`10-12B`, `10-KT` included
/// alongside `10-K`/`10-K/A`/`10-Q`, matching `lib/prepare_edgar_data.py`'s
/// actual (if under-documented) filter and `lib/edgar.py`'s own
/// `LIKE '10-%'` query - `edgar-backend.md` §2.1's decision). Entries whose
/// URL or date cannot be parsed are skipped.
pub async fn fetch_quarter_rows(edgar: &Edgar, period: EdgarPeriod) -> anyhow::Result<Vec<CatalogRow>> {
    let entries = edgar.get_period_filings(period, None).await?;
    let mut rows = Vec::new();
    for entry in entries.iter().filter(|e| e.form_type.starts_with("10-")) {
        let (accession, (y, m, d)) = match (extract_accession(&entry.url), split_date_filed(&entry.date_filed)) {
            (Some(a), Some(d)) => (a, d),
            _ => continue,
        };
        rows.push(CatalogRow {
            cik: entry.cik,
            company_name: entry.company_name.clone(),
            form_type: entry.form_type.clone(),
            year: y,
            month: m as i32,
            day: d as i32,
            accession,
            url: entry.url.clone(),
        });
    }
    Ok(rows)
}

/// Writes `rows` to a `.feather` file at `out_path`, with `metadata` (for
/// example the quarters covered and when it was built) stored in the Arrow
/// schema so the file describes itself. Rows are de-duplicated by (CIK,
/// accession number): a filing appears once per company however many quarterly
/// indexes listed it. The accession number alone is NOT the key - co-registrants
/// (a parent and its subsidiaries, trusts and their depositors) file under one
/// accession number, and each is its own catalog row. The file is written to a temporary sibling and renamed
/// into place, so a failed or interrupted run never leaves a half-written
/// catalog where the server will read it. Fails, writing nothing, on zero
/// rows. Returns the row count written.
pub fn write_catalog_rows(
    rows: &[CatalogRow],
    out_path: &Path,
    metadata: std::collections::HashMap<String, String>,
) -> anyhow::Result<usize> {
    let mut seen = std::collections::HashSet::new();
    let unique: Vec<&CatalogRow> = rows.iter().filter(|r| seen.insert((r.cik, r.accession.clone()))).collect();
    if unique.is_empty() {
        anyhow::bail!("no 10-x filings to write - refusing to produce an empty catalog");
    }

    let mut metadata = metadata;
    metadata.insert("rows".into(), unique.len().to_string());
    let schema = Arc::new(catalog_schema().as_ref().clone().with_metadata(metadata));
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(UInt64Array::from(unique.iter().map(|r| r.cik).collect::<Vec<_>>())),
            Arc::new(StringArray::from(unique.iter().map(|r| r.company_name.as_str()).collect::<Vec<_>>())),
            Arc::new(StringArray::from(unique.iter().map(|r| r.form_type.as_str()).collect::<Vec<_>>())),
            Arc::new(Int32Array::from(unique.iter().map(|r| r.year).collect::<Vec<_>>())),
            Arc::new(Int32Array::from(unique.iter().map(|r| r.month).collect::<Vec<_>>())),
            Arc::new(Int32Array::from(unique.iter().map(|r| r.day).collect::<Vec<_>>())),
            Arc::new(StringArray::from(unique.iter().map(|r| r.accession.as_str()).collect::<Vec<_>>())),
            Arc::new(StringArray::from(unique.iter().map(|r| r.url.as_str()).collect::<Vec<_>>())),
        ],
    )?;

    if let Some(parent) = out_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp_path = out_path.with_extension("feather.tmp");
    {
        let file = std::fs::File::create(&tmp_path)?;
        let mut writer = FileWriter::try_new(file, &schema)?;
        writer.write(&batch)?;
        writer.finish()?;
    }
    std::fs::rename(&tmp_path, out_path)?;
    Ok(unique.len())
}

/// Single-quarter convenience (the original entry point): fetch one quarter
/// and write it. Kept for the experiments that call it.
pub async fn write_catalog_feather(
    edgar: &Edgar,
    period: EdgarPeriod,
    out_path: &Path,
) -> anyhow::Result<usize> {
    let rows = fetch_quarter_rows(edgar, period).await?;
    write_catalog_rows(&rows, out_path, std::collections::HashMap::new())
}

/// A single row from the catalog, matching what `lib/edgar.py`'s
/// `get_all_ciks`/`get_all_details` return per company.
#[derive(Debug, Clone, serde::Serialize)]
pub struct CatalogEntry {
    pub cik: u64,
    pub company_name: String,
    pub form_type: String,
    pub year: i32,
    pub month: i32,
    pub day: i32,
    pub accession: String,
}

/// One filing, as `lib/edgar.py`'s `get_all_details` attaches it under
/// a company's `forms` dict - same two fields, same key shape
/// (`"{year}-{month}-{day}-{accession_no_dashes}"`), same
/// `filing_idx_url` construction (`EDGARURI`+`EDGARSERVER`+
/// `EDGARARCHIVES`, `lib/edgar.py`'s constants).
#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FormEntry {
    pub filing_index: String,
    pub form_type: String,
}

/// One company, grouped from its individual filing rows - matches
/// `lib/edgar.py`'s `get_all_details` grouping-by-company-name loop
/// (`tmp_companies[company_name]['forms'][accession_key] = form`), not
/// just a flat list of filing rows. `company_name` is normalized the
/// same way V3 does (`.upper()`, trailing `.` stripped) so V3 and V4
/// group the same real-world rows into the same companies.
#[derive(Debug, Clone, serde::Serialize)]
pub struct GroupedCompany {
    pub cik: u64,
    pub company_name: String,
    pub forms: BTreeMap<String, FormEntry>,
}

fn filing_index_url(cik: u64, accession: &str) -> String {
    let accession_no_dashes = accession.replace('-', "");
    format!(
        "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{accession}-index.html"
    )
}

/// Groups flat `CatalogEntry` rows into per-company entries with a
/// `forms` map - the shape `lib/edgar.py`'s `get_all_details` builds
/// query-time from its own SQL result set. `company_name` is the group
/// key (matching V3's `tmp_companies[company_name]` dict exactly), not
/// `(cik, company_name)` - real-world data should never have one name
/// mapping to two CIKs within a single quarter's filings, and grouping
/// on the same key V3 uses is what makes this a fair parity comparison.
fn group_by_company(matches: Vec<CatalogEntry>) -> Vec<GroupedCompany> {
    let mut by_name: BTreeMap<String, GroupedCompany> = BTreeMap::new();
    for m in matches {
        let company_name = m.company_name.to_uppercase();
        let company_name = company_name.trim_end_matches('.').to_string();
        let accession_no_dashes = m.accession.replace('-', "");
        let accession_key = format!("{}-{}-{}-{}", m.year, m.month, m.day, accession_no_dashes);
        let filing_index = filing_index_url(m.cik, &m.accession);

        let entry = by_name
            .entry(company_name.clone())
            .or_insert_with(|| GroupedCompany {
                cik: m.cik,
                company_name: company_name.clone(),
                forms: BTreeMap::new(),
            });
        entry.forms.insert(
            accession_key,
            FormEntry {
                filing_index,
                form_type: m.form_type,
            },
        );
    }
    by_name.into_values().collect()
}

pub struct EdgarCatalog {
    ctx: SessionContext,
}

impl EdgarCatalog {
    /// Loads the `.feather` catalog `write_catalog_feather` produced.
    /// Same `read_arrow`/`ArrowReadOptions` pattern
    /// `experiments/edgar-index-query/` and `experiments/df-spike/`
    /// already validated against real Mediumroast/EDGAR files.
    pub async fn open(path: &Path) -> anyhow::Result<Self> {
        let ctx = SessionContext::new();
        let opts = ArrowReadOptions {
            file_extension: ".feather",
            ..ArrowReadOptions::default()
        };
        let df = ctx
            .read_arrow(path.to_string_lossy().as_ref(), opts)
            .await?;
        ctx.register_table("edgar_catalog", df.into_view())?;
        Ok(Self { ctx })
    }

    /// What the experimental SQL endpoint (`docs/plans/v4-sql-endpoint.md`) is
    /// built from: this catalog's session and its table name.
    pub fn query_source(&self) -> (SessionContext, Vec<String>) {
        (self.ctx.clone(), vec!["edgar_catalog".to_string()])
    }

    /// Company-name search. **Decided
    /// (`docs/plans/v4-server-prototype.md` §6, 2026-09-28): matches
    /// V3's `LIKE '%name%'` behavior exactly**, for an honest
    /// apples-to-apples comparison against the Python service - not the
    /// similarity-search machinery `company-dns-sic` uses for SIC data.
    /// SQLite's `LIKE` is case-insensitive for ASCII by default, so
    /// this uses DataFusion's `ILIKE` (not `LIKE`, which is
    /// case-sensitive) to match that behavior, not just the operator's
    /// name.
    ///
    /// **One addition (2026-10-04), which never changes a result V3 would
    /// have returned:** when that V3-style match finds nothing, the search is
    /// retried with punctuation ignored on both sides. The catalog stores
    /// "Apple Inc." and people type the legal name, "Apple, Inc."; V3's exact
    /// substring match returns nothing for it, and the EDGAR Explorer showed
    /// an error. Anything V3 matched is returned exactly as before.
    pub async fn find_by_name(&self, name: &str) -> anyhow::Result<Vec<CatalogEntry>> {
        let escaped = name.replace('\'', "''");
        let sql = format!(
            "SELECT cik, company_name, form_type, year, month, day, accession \
             FROM edgar_catalog WHERE company_name ILIKE '%{escaped}%' \
             ORDER BY year DESC, month DESC, day DESC"
        );
        let exact = self.run_catalog_query(&sql).await?;
        if !exact.is_empty() {
            return Ok(exact);
        }

        // The normalised query contains only [a-z0-9 ], so it cannot carry a
        // quote or a LIKE wildcard.
        let normalised = normalize_for_match(name);
        if normalised.is_empty() {
            return Ok(exact);
        }
        let sql = format!(
            "SELECT cik, company_name, form_type, year, month, day, accession \
             FROM edgar_catalog \
             WHERE trim(regexp_replace(lower(company_name), '[^a-z0-9]+', ' ', 'g')) LIKE '%{normalised}%' \
             ORDER BY year DESC, month DESC, day DESC"
        );
        self.run_catalog_query(&sql).await
    }

    /// V3-parity company-name search, grouped exactly like
    /// `lib/edgar.py`'s `get_all_details`: one entry per company, each
    /// with a `forms` map of every matching filing, not one entry per
    /// filing row. Backs `detail`/`summary` (`v4-server-prototype.md`
    /// §5.3) - callers decide whether to additionally merge in live
    /// firmographics per company (`detail`) or not (`summary`), the
    /// same `firmographics=True`/`False` split V3's single method makes
    /// via a parameter.
    pub async fn find_grouped_by_name(&self, name: &str) -> anyhow::Result<Vec<GroupedCompany>> {
        let matches = self.find_by_name(name).await?;
        Ok(group_by_company(matches))
    }

    /// Direct CIK lookup - the durable-identifier path
    /// (`go-duckdb-rewrite.md` §2), preferred over name search wherever
    /// the caller already has a CIK.
    pub async fn find_by_cik(&self, cik: u64) -> anyhow::Result<Vec<CatalogEntry>> {
        let sql = format!(
            "SELECT cik, company_name, form_type, year, month, day, accession \
             FROM edgar_catalog WHERE cik = {cik} \
             ORDER BY year DESC, month DESC, day DESC"
        );
        self.run_catalog_query(&sql).await
    }

    async fn run_catalog_query(&self, sql: &str) -> anyhow::Result<Vec<CatalogEntry>> {
        let df = self.ctx.sql(sql).await?;
        let batches = df.collect().await?;

        let mut out = Vec::new();
        for batch in &batches {
            let ciks = batch
                .column(0)
                .as_any()
                .downcast_ref::<UInt64Array>()
                .unwrap();
            let names = batch
                .column(1)
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap();
            let forms = batch
                .column(2)
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap();
            let years = batch
                .column(3)
                .as_any()
                .downcast_ref::<Int32Array>()
                .unwrap();
            let months = batch
                .column(4)
                .as_any()
                .downcast_ref::<Int32Array>()
                .unwrap();
            let days = batch
                .column(5)
                .as_any()
                .downcast_ref::<Int32Array>()
                .unwrap();
            let accessions = batch
                .column(6)
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap();

            for i in 0..batch.num_rows() {
                out.push(CatalogEntry {
                    cik: ciks.value(i),
                    company_name: names.value(i).to_string(),
                    form_type: forms.value(i).to_string(),
                    year: years.value(i),
                    month: months.value(i),
                    day: days.value(i),
                    accession: accessions.value(i).to_string(),
                });
            }
        }
        Ok(out)
    }
}

/// Lower-cases and replaces every run of non-alphanumeric characters with a
/// single space, so "Apple, Inc." and "APPLE INC" both become "apple inc".
/// Mirrors the SQL in [`EdgarCatalog::find_by_name`]'s fallback.
fn normalize_for_match(name: &str) -> String {
    name.chars()
        .map(|c| if c.is_ascii_alphanumeric() { c.to_ascii_lowercase() } else { ' ' })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use datafusion::arrow::array::{Int32Array, StringArray, UInt64Array};
    use datafusion::arrow::datatypes::{DataType, Field, Schema};
    use datafusion::arrow::record_batch::RecordBatch;
    use datafusion::datasource::MemTable;
    use std::sync::Arc;

    fn catalog(names: &[(u64, &str)]) -> EdgarCatalog {
        let schema = Arc::new(Schema::new(vec![
            Field::new("cik", DataType::UInt64, false),
            Field::new("company_name", DataType::Utf8, false),
            Field::new("form_type", DataType::Utf8, false),
            Field::new("year", DataType::Int32, false),
            Field::new("month", DataType::Int32, false),
            Field::new("day", DataType::Int32, false),
            Field::new("accession", DataType::Utf8, false),
        ]));
        let n = names.len();
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(UInt64Array::from(names.iter().map(|x| x.0).collect::<Vec<_>>())),
                Arc::new(StringArray::from(names.iter().map(|x| x.1).collect::<Vec<_>>())),
                Arc::new(StringArray::from(vec!["10-Q"; n])),
                Arc::new(Int32Array::from(vec![2025; n])),
                Arc::new(Int32Array::from(vec![5; n])),
                Arc::new(Int32Array::from(vec![1; n])),
                Arc::new(StringArray::from((0..n).map(|i| format!("0000000000-25-{i:06}")).collect::<Vec<_>>())),
            ],
        )
        .unwrap();
        let ctx = SessionContext::new();
        ctx.register_table("edgar_catalog", Arc::new(MemTable::try_new(schema, vec![vec![batch]]).unwrap())).unwrap();
        EdgarCatalog { ctx }
    }

    #[test]
    fn normalising_ignores_case_and_punctuation() {
        assert_eq!(normalize_for_match("Apple, Inc."), "apple inc");
        assert_eq!(normalize_for_match("  AT&T  Corp. "), "at t corp");
        assert_eq!(normalize_for_match("%_';--"), "");
    }

    #[tokio::test]
    async fn v3_style_match_is_unchanged_and_punctuation_only_rescues_misses() {
        let cat = catalog(&[
            (320193, "Apple Inc."),
            (1710495, "PINEAPPLE EXPRESS CANNABIS Co"),
            (1318605, "Tesla, Inc."),
        ]);
        // V3 matched this substring, so it still returns exactly what V3 did
        // (including the mid-word match); the fallback must not run.
        let apple = cat.find_by_name("apple").await.unwrap();
        assert_eq!(apple.len(), 2);

        // V3 found nothing for the legal name with a comma; now it does.
        let legal = cat.find_by_name("Apple, Inc.").await.unwrap();
        assert!(legal.iter().any(|e| e.company_name == "Apple Inc." && e.cik == 320193));
        // ...and the other direction: query without the comma, catalog with it.
        let tesla = cat.find_by_name("Tesla Inc").await.unwrap();
        assert_eq!(tesla.len(), 1);
        assert_eq!(tesla[0].cik, 1318605);

        // Genuine misses stay misses; wildcard characters stay literal.
        assert!(cat.find_by_name("Nonexistent Corp").await.unwrap().is_empty());
        assert!(cat.find_by_name("%").await.unwrap().len() <= 3);
        assert!(cat.find_by_name("%_';--").await.unwrap().is_empty());
    }

    fn row(cik: u64, name: &str, accession: &str, year: i32, month: i32) -> CatalogRow {
        CatalogRow {
            cik,
            company_name: name.into(),
            form_type: "10-Q".into(),
            year,
            month,
            day: 1,
            accession: accession.into(),
            url: format!("https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt"),
        }
    }

    #[tokio::test]
    async fn written_catalog_round_trips_dedupes_and_describes_itself() {
        let dir = std::env::temp_dir().join(format!("catalog-test-{}", std::process::id()));
        let out = dir.join("cat.feather");
        // The same filing listed by two quarterly indexes must appear once.
        let rows = vec![
            row(320193, "Apple Inc.", "0000320193-25-000001", 2025, 5),
            row(320193, "Apple Inc.", "0000320193-25-000001", 2025, 5),
            row(789019, "MICROSOFT CORP", "0000789019-24-000002", 2024, 11),
            // Co-registrants share one accession number; both must survive.
            row(1002910, "AMEREN CORP", "0001002910-25-000098", 2025, 2),
            row(100826, "UNION ELECTRIC CO", "0001002910-25-000098", 2025, 2),
        ];
        let meta = std::collections::HashMap::from([("last_quarter".to_string(), "2025Q2".to_string())]);
        assert_eq!(write_catalog_rows(&rows, &out, meta).unwrap(), 4);
        assert!(!out.with_extension("feather.tmp").exists(), "temporary file must be renamed away");

        // The real reader reads it back, across both years.
        let cat = EdgarCatalog::open(&out).await.unwrap();
        assert_eq!(cat.find_by_cik(320193).await.unwrap().len(), 1);
        assert_eq!(cat.find_by_cik(789019).await.unwrap()[0].year, 2024);

        // The schema carries the metadata, plus the row count it adds itself.
        let reader = datafusion::arrow::ipc::reader::FileReader::try_new(std::fs::File::open(&out).unwrap(), None).unwrap();
        let md = reader.schema().metadata().clone();
        assert_eq!(md.get("last_quarter").map(String::as_str), Some("2025Q2"));
        assert_eq!(md.get("rows").map(String::as_str), Some("4"));
        assert_eq!(cat.find_by_cik(100826).await.unwrap().len(), 1);
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn an_empty_catalog_is_refused_and_leaves_nothing_behind() {
        let dir = std::env::temp_dir().join(format!("catalog-empty-{}", std::process::id()));
        let out = dir.join("cat.feather");
        assert!(write_catalog_rows(&[], &out, Default::default()).is_err());
        assert!(!out.exists());
    }
}
