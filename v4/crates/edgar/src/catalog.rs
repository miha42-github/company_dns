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

/// Fetches a quarter's filing index via `edgarkit`, filters to the
/// `'10-%'` form family (kept broad - `10-D`, `10-12G`/`10-12B`,
/// `10-KT` included alongside `10-K`/`10-K/A`/`10-Q`, matching
/// `lib/prepare_edgar_data.py`'s actual (if under-documented) filter
/// and `lib/edgar.py`'s own `LIKE '10-%'` query - `edgar-backend.md`
/// §2.1's decision), and writes the result to a `.feather` file at
/// `out_path`. Returns the row count written.
pub async fn write_catalog_feather(
    edgar: &Edgar,
    period: EdgarPeriod,
    out_path: &Path,
) -> anyhow::Result<usize> {
    let entries = edgar.get_period_filings(period, None).await?;
    let ten_series: Vec<_> = entries
        .iter()
        .filter(|e| e.form_type.starts_with("10-"))
        .collect();

    let mut ciks = Vec::with_capacity(ten_series.len());
    let mut companies = Vec::with_capacity(ten_series.len());
    let mut forms = Vec::with_capacity(ten_series.len());
    let mut years = Vec::with_capacity(ten_series.len());
    let mut months = Vec::with_capacity(ten_series.len());
    let mut days = Vec::with_capacity(ten_series.len());
    let mut accessions = Vec::with_capacity(ten_series.len());
    let mut urls = Vec::with_capacity(ten_series.len());

    for entry in &ten_series {
        let (accession, date_parts) = match (
            extract_accession(&entry.url),
            split_date_filed(&entry.date_filed),
        ) {
            (Some(a), Some(d)) => (a, d),
            _ => continue,
        };
        ciks.push(entry.cik);
        companies.push(entry.company_name.clone());
        forms.push(entry.form_type.clone());
        years.push(date_parts.0);
        months.push(date_parts.1 as i32);
        days.push(date_parts.2 as i32);
        accessions.push(accession);
        urls.push(entry.url.clone());
    }

    let schema = catalog_schema();
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(UInt64Array::from(ciks)),
            Arc::new(StringArray::from(companies)),
            Arc::new(StringArray::from(forms)),
            Arc::new(Int32Array::from(years)),
            Arc::new(Int32Array::from(months)),
            Arc::new(Int32Array::from(days)),
            Arc::new(StringArray::from(accessions)),
            Arc::new(StringArray::from(urls)),
        ],
    )?;
    let rows_written = batch.num_rows();

    if let Some(parent) = out_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let file = std::fs::File::create(out_path)?;
    let mut writer = FileWriter::try_new(file, &schema)?;
    writer.write(&batch)?;
    writer.finish()?;

    Ok(rows_written)
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

    /// Company-name search. **Decided
    /// (`docs/plans/v4-server-prototype.md` §6, 2026-09-28): matches
    /// V3's `LIKE '%name%'` behavior exactly**, for an honest
    /// apples-to-apples comparison against the Python service - not the
    /// similarity-search machinery `company-dns-sic` uses for SIC data.
    /// SQLite's `LIKE` is case-insensitive for ASCII by default, so
    /// this uses DataFusion's `ILIKE` (not `LIKE`, which is
    /// case-sensitive) to match that behavior, not just the operator's
    /// name.
    pub async fn find_by_name(&self, name: &str) -> anyhow::Result<Vec<CatalogEntry>> {
        let escaped = name.replace('\'', "''");
        let sql = format!(
            "SELECT cik, company_name, form_type, year, month, day, accession \
             FROM edgar_catalog WHERE company_name ILIKE '%{escaped}%' \
             ORDER BY year DESC, month DESC, day DESC"
        );
        self.run_catalog_query(&sql).await
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
