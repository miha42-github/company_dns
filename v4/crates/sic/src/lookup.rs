//! V3-parity US SIC lookups (`docs/plans/v4-server-prototype.md` §5.2),
//! backed by a DataFusion query against the flat, denormalized
//! `.feather` table instead of `lib/sic.py`'s four normalized SQLite
//! tables (`sic`, `major_groups`, `industry_groups`, `divisions`).
//!
//! **Naming note, easy to get backwards**: V3's hierarchy
//! (division -> major_group -> industry_group -> sic) uses different
//! names than Mediumroast's flat schema
//! (section -> division -> group -> class -> subclass,
//! `go-duckdb-rewrite.md` §7.2). The mapping this module uses:
//!
//! | V3 (`lib/sic.py`)      | Mediumroast `.feather` column |
//! |-------------------------|-------------------------------|
//! | `division` (A-Z letter) | `section_id`/`section_desc`   |
//! | `major_group` (2-digit) | `division_id`/`division_desc` |
//! | `industry_group` (3-digit) | `group_id`/`group_desc`    |
//! | `sic` (4-digit code)    | `class_id`/`class_desc`       |
//!
//! Every lookup uses DataFusion's `ILIKE` (not `LIKE`, which is
//! case-sensitive) to match SQLite's default case-insensitive `LIKE`
//! behavior - **decided (`v4-server-prototype.md` §6, 2026-09-28): V4
//! matches V3's fuzzy-match semantics exactly**, not something more
//! sophisticated, deferred until more company data justifies it.
//! `DISTINCT` is required throughout since the flat table repeats a
//! division/group/class value on every row under it.

use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct SicMatch {
    pub section_id: String,
    pub section_desc: String,
    pub division_id: String,
    pub division_desc: String,
    pub group_id: String,
    pub group_desc: String,
    pub class_id: String,
    pub class_desc: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct DivisionMatch {
    pub section_id: String,
    pub section_desc: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct MajorGroupMatch {
    pub division_id: String,
    pub division_desc: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct IndustryGroupMatch {
    pub group_id: String,
    pub group_desc: String,
}

impl super::SicCatalog {
    /// V3's `GET /sic/description/{sic_desc}` (`get_all_sic_by_name`).
    pub async fn find_by_description(&self, query: &str) -> anyhow::Result<Vec<SicMatch>> {
        let escaped = query.replace('\'', "''");
        let sql = format!(
            "SELECT DISTINCT section_id, section_desc, division_id, division_desc, \
             group_id, group_desc, class_id, class_desc \
             FROM sic_data WHERE class_desc ILIKE '%{escaped}%'"
        );
        self.run_sic_query(&sql).await
    }

    /// V3's `GET /sic/code/{sic_code}` (`get_all_sic_by_no`).
    pub async fn find_by_code(&self, code: &str) -> anyhow::Result<Vec<SicMatch>> {
        let escaped = code.replace('\'', "''");
        let sql = format!(
            "SELECT DISTINCT section_id, section_desc, division_id, division_desc, \
             group_id, group_desc, class_id, class_desc \
             FROM sic_data WHERE class_id ILIKE '%{escaped}%'"
        );
        self.run_sic_query(&sql).await
    }

    /// V3's `GET /sic/division/{division_code}`
    /// (`get_division_desc_by_id`) - V3's "division" is a letter (A-Z),
    /// the flat table's `section_id`.
    pub async fn find_division(&self, code: &str) -> anyhow::Result<Vec<DivisionMatch>> {
        let escaped = code.replace('\'', "''");
        let sql = format!(
            "SELECT DISTINCT section_id, section_desc FROM sic_data \
             WHERE section_id ILIKE '%{escaped}%'"
        );
        let df = self.ctx.sql(&sql).await?;
        let batches = df.collect().await?;
        let mut out = Vec::new();
        for batch in &batches {
            let ids = string_col(batch, 0);
            let descs = string_col(batch, 1);
            for i in 0..batch.num_rows() {
                out.push(DivisionMatch {
                    section_id: ids.value(i).to_string(),
                    section_desc: descs.value(i).to_string(),
                });
            }
        }
        Ok(out)
    }

    /// V3's `GET /sic/major/{major_code}` (`get_all_major_group_by_no`)
    /// - V3's "major group" (2-digit) is the flat table's `division_id`.
    pub async fn find_major_group(&self, code: &str) -> anyhow::Result<Vec<MajorGroupMatch>> {
        let escaped = code.replace('\'', "''");
        let sql = format!(
            "SELECT DISTINCT division_id, division_desc FROM sic_data \
             WHERE division_id ILIKE '%{escaped}%'"
        );
        let df = self.ctx.sql(&sql).await?;
        let batches = df.collect().await?;
        let mut out = Vec::new();
        for batch in &batches {
            let ids = string_col(batch, 0);
            let descs = string_col(batch, 1);
            for i in 0..batch.num_rows() {
                out.push(MajorGroupMatch {
                    division_id: ids.value(i).to_string(),
                    division_desc: descs.value(i).to_string(),
                });
            }
        }
        Ok(out)
    }

    /// V3's `GET /sic/industry/{industry_code}`
    /// (`get_all_industry_group_by_no`) - V3's "industry group"
    /// (3-digit) is the flat table's `group_id`.
    pub async fn find_industry_group(&self, code: &str) -> anyhow::Result<Vec<IndustryGroupMatch>> {
        let escaped = code.replace('\'', "''");
        let sql = format!(
            "SELECT DISTINCT group_id, group_desc FROM sic_data \
             WHERE group_id ILIKE '%{escaped}%'"
        );
        let df = self.ctx.sql(&sql).await?;
        let batches = df.collect().await?;
        let mut out = Vec::new();
        for batch in &batches {
            let ids = string_col(batch, 0);
            let descs = string_col(batch, 1);
            for i in 0..batch.num_rows() {
                out.push(IndustryGroupMatch {
                    group_id: ids.value(i).to_string(),
                    group_desc: descs.value(i).to_string(),
                });
            }
        }
        Ok(out)
    }

    async fn run_sic_query(&self, sql: &str) -> anyhow::Result<Vec<SicMatch>> {
        let df = self.ctx.sql(sql).await?;
        let batches = df.collect().await?;
        let mut out = Vec::new();
        for batch in &batches {
            let section_id = string_col(batch, 0);
            let section_desc = string_col(batch, 1);
            let division_id = string_col(batch, 2);
            let division_desc = string_col(batch, 3);
            let group_id = string_col(batch, 4);
            let group_desc = string_col(batch, 5);
            let class_id = string_col(batch, 6);
            let class_desc = string_col(batch, 7);
            for i in 0..batch.num_rows() {
                out.push(SicMatch {
                    section_id: section_id.value(i).to_string(),
                    section_desc: section_desc.value(i).to_string(),
                    division_id: division_id.value(i).to_string(),
                    division_desc: division_desc.value(i).to_string(),
                    group_id: group_id.value(i).to_string(),
                    group_desc: group_desc.value(i).to_string(),
                    class_id: class_id.value(i).to_string(),
                    class_desc: class_desc.value(i).to_string(),
                });
            }
        }
        Ok(out)
    }
}

fn string_col(
    batch: &datafusion::arrow::record_batch::RecordBatch,
    idx: usize,
) -> &datafusion::arrow::array::LargeStringArray {
    batch
        .column(idx)
        .as_any()
        .downcast_ref::<datafusion::arrow::array::LargeStringArray>()
        .unwrap_or_else(|| panic!("column {idx} is not LargeStringArray"))
}
