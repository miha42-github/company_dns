//! Per-system code lookups over the flat tables, and V3's exact response shapes -
//! `docs/plans/v4-release-to-staging.md` (New E, and the V2.0 aliases).
//!
//! V3 serves, for each classification system, one lookup per hierarchy level plus a description
//! search (`lib/sic.py`, `lib/eu_sic.py`, `lib/international_sic.py`, `lib/japan_sic.py`). V4 holds every
//! system as one flat table (`section`, `division`, `group`, `class` columns), so one query serves them all.
//! V3 names the levels differently per system:
//!
//! | flat level | US SIC (V3)      | EU NACE / ISIC (V3) | Japan SIC (V3)  |
//! |------------|------------------|---------------------|-----------------|
//! | `section`  | `division` (A-Z) | `section`           | `division` (A-T)|
//! | `division` | `major_group`    | `division`          | `major_group`   |
//! | `group`    | `industry_group` | `group`             | `group`         |
//! | `class`    | `sic` (4 digits) | `class`             | `industry_group`|
//!
//! Matching is V3's: a case-insensitive substring match (`LIKE '%q%'`) on the level's code, or on the
//! class description. `find_in_system` returns the rows; `v3_reply` shapes them exactly as V3 answered
//! (a dictionary keyed by code, or by description, with a `total`, and V3's own field names, messages and
//! module strings). The V4.0 paths return the rows themselves.
//!
//! Known, intentional differences from V3 (recorded in `docs/plans/v4-release-to-staging.md`): the
//! `dependencies` block is V4's, a no-match is a JSON 404 envelope (V3 answered with an HTML 404 page), V4's
//! Japan and NACE data are the corrected files, and V3's US `division` answer also carries a
//! `full_description` narrative that V4's data does not have (it is returned empty).

use datafusion::arrow::array::LargeStringArray;
use serde::Serialize;
use serde_json::{json, Map, Value};

use crate::company_match::{ISIC, JAPAN, NACE, US};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum System {
    Us,
    EuNace,
    Isic,
    Japan,
}

impl System {
    /// The label the system is registered under (`SicCatalog::register_system`).
    pub fn label(self) -> &'static str {
        match self {
            System::Us => US,
            System::EuNace => NACE,
            System::Isic => ISIC,
            System::Japan => JAPAN,
        }
    }
}

/// A level of the flat hierarchy. Each system's V3 name for it is in the module table.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Level {
    Section,
    Division,
    Group,
    Class,
}

impl Level {
    fn id_col(self) -> &'static str {
        match self {
            Level::Section => "section_id",
            Level::Division => "division_id",
            Level::Group => "group_id",
            Level::Class => "class_id",
        }
    }

    /// Columns selected for this level: its own and its parents', never its children's.
    fn columns(self) -> &'static [&'static str] {
        match self {
            Level::Section => &["section_id", "section_desc"],
            Level::Division => &["section_id", "section_desc", "division_id", "division_desc"],
            Level::Group => &["section_id", "section_desc", "division_id", "division_desc", "group_id", "group_desc"],
            Level::Class => &[
                "section_id", "section_desc", "division_id", "division_desc", "group_id", "group_desc", "class_id", "class_desc",
            ],
        }
    }
}

/// One matched row at a level: that level and its parents (deeper columns are `None` and omitted from JSON).
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct LevelRow {
    pub section_id: String,
    pub section_desc: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub division_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub division_desc: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group_desc: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub class_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub class_desc: Option<String>,
}

fn col(batch: &datafusion::arrow::record_batch::RecordBatch, idx: usize) -> Option<&LargeStringArray> {
    batch.column(idx).as_any().downcast_ref::<LargeStringArray>()
}

impl super::SicCatalog {
    /// Rows at `level` whose code (or, with `by_description`, class description) contains `query`,
    /// case-insensitively, in code order. `Ok(None)` means the system is not loaded on this server.
    pub async fn find_in_system(
        &self,
        system: System,
        level: Level,
        query: &str,
        by_description: bool,
    ) -> anyhow::Result<Option<Vec<LevelRow>>> {
        let Some(table) = self
            .systems
            .iter()
            .find(|s| s.source_label == system.label())
            .map(|s| s.table_name.clone())
        else {
            return Ok(None);
        };
        let level = if by_description { Level::Class } else { level };
        let filter = if by_description { "class_desc" } else { level.id_col() };
        let escaped = query.replace('\'', "''");
        let cols = level.columns();
        let sql = format!(
            "SELECT DISTINCT {} FROM {table} WHERE {filter} ILIKE '%{escaped}%' ORDER BY {}",
            cols.join(", "),
            level.id_col()
        );
        let batches = self.ctx.sql(&sql).await?.collect().await?;
        let mut rows = Vec::new();
        for batch in &batches {
            let get = |i: usize, r: usize| -> Option<String> {
                if i >= cols.len() {
                    return None;
                }
                col(batch, i).map(|a| a.value(r).to_string())
            };
            for r in 0..batch.num_rows() {
                rows.push(LevelRow {
                    section_id: get(0, r).unwrap_or_default(),
                    section_desc: get(1, r).unwrap_or_default(),
                    division_id: get(2, r),
                    division_desc: get(3, r),
                    group_id: get(4, r),
                    group_desc: get(5, r),
                    class_id: get(6, r),
                    class_desc: get(7, r),
                });
            }
        }
        Ok(Some(rows))
    }
}

// ---------------------------------------------------------------------------
// V3's response shapes
// ---------------------------------------------------------------------------

/// V3's answer for one lookup: the status, message, module string and `data`.
#[derive(Debug, Clone, PartialEq)]
pub struct V3Reply {
    pub code: u16,
    pub message: String,
    pub module: String,
    pub data: Value,
}

fn s(v: &Option<String>) -> String {
    v.clone().unwrap_or_default()
}

/// What V3 called this level in this system: (data key, message word, method suffix, module class).
fn names(system: System, level: Level, by_description: bool) -> (&'static str, &'static str, String, &'static str) {
    let class = match system {
        System::Us => "SICQueries",
        System::EuNace => "EuSICQueries",
        System::Isic => "InternationalSICQueries",
        System::Japan => "JapanSICQueries",
    };
    match system {
        System::Us => match level {
            Level::Section => ("division", "Division", "get_division_desc_by_id".into(), class),
            Level::Division => ("major_groups", "Major group", "get_all_major_group_by_no".into(), class),
            Level::Group => ("industry_groups", "Industry group", "get_all_industry_group_by_no".into(), class),
            Level::Class => (
                "sics",
                "SIC",
                if by_description { "get_all_sic_by_name" } else { "get_all_sic_by_no" }.into(),
                class,
            ),
        },
        System::EuNace | System::Isic => {
            let (key, word, method) = match level {
                Level::Section => ("sections", "section", "get_section_by_code"),
                Level::Division => ("divisions", "division", "get_division_by_code"),
                Level::Group => ("groups", "group", "get_group_by_code"),
                Level::Class => ("classes", "class", if by_description { "get_class_by_description" } else { "get_class_by_code" }),
            };
            (key, word, method.into(), class)
        }
        System::Japan => {
            let (key, word, method) = match level {
                Level::Section => ("divisions", "division", "get_division_by_code"),
                Level::Division => ("major_groups", "major group", "get_major_group_by_code"),
                Level::Group => ("groups", "group", "get_group_by_code"),
                Level::Class => (
                    "industry_groups",
                    "industry group",
                    if by_description { "get_industry_group_by_description" } else { "get_industry_group_by_code" },
                ),
            };
            (key, word, method.into(), class)
        }
    }
}

fn first_upper(w: &str) -> String {
    let mut c = w.chars();
    match c.next() {
        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
        None => String::new(),
    }
}

/// The two message strings V3 used for this lookup: (found, not found).
fn messages(system: System, level: Level, by_description: bool, word: &str, query: &str) -> (String, String) {
    let how = if by_description { "description query" } else { "query" };
    match system {
        System::Us => {
            let none = match level {
                Level::Section => "No Division found".to_string(),
                Level::Division => "No Major Group found".to_string(),
                Level::Group => "No Industry Group found".to_string(),
                Level::Class => if by_description { "No SICs found" } else { "No SIC found" }.to_string(),
            };
            // V3's US answers say "for query" even for a description search.
            (format!("{word} data has been returned for query [{query}]."), format!("{none} for query [{query}]."))
        }
        System::EuNace => (
            format!("EU SIC {word} data has been returned for {how} [{query}]."),
            format!("No EU SIC {word} found for {how} [{query}]."),
        ),
        System::Isic => (
            format!("{} data has been returned for {how} [{query}].", first_upper(word)),
            format!("No {word} found for {how} [{query}]."),
        ),
        System::Japan => (
            format!("Japan SIC {word} data has been returned for {how} [{query}]."),
            format!("No Japan SIC {word} found for {how} [{query}]."),
        ),
    }
}

/// One entry of V3's data dictionary: its key (the code, or the description when searching by description)
/// and the fields V3 put under it.
fn entry(system: System, level: Level, by_description: bool, r: &LevelRow) -> (String, Value) {
    let id = match level {
        Level::Section => r.section_id.clone(),
        Level::Division => s(&r.division_id),
        Level::Group => s(&r.group_id),
        Level::Class => s(&r.class_id),
    };
    let desc = match level {
        Level::Section => r.section_desc.clone(),
        Level::Division => s(&r.division_desc),
        Level::Group => s(&r.group_desc),
        Level::Class => s(&r.class_desc),
    };
    let mut m = Map::new();
    let put = |m: &mut Map<String, Value>, k: &str, v: String| {
        m.insert(k.to_string(), Value::String(v));
    };
    // Searching by description keys the entry by the description and carries the code as a field.
    if by_description {
        put(&mut m, "code", id.clone());
    } else {
        put(&mut m, "description", desc.clone());
    }
    match system {
        System::Us => match level {
            Level::Section => {
                // V3's division narrative has no counterpart in V4's data.
                m.insert("full_description".into(), Value::String(String::new()));
            }
            Level::Division => put(&mut m, "division", r.section_id.clone()),
            Level::Group => {
                put(&mut m, "division", r.section_id.clone());
                put(&mut m, "major_group", s(&r.division_id));
            }
            Level::Class => {
                put(&mut m, "division", r.section_id.clone());
                put(&mut m, "division_desc", r.section_desc.clone());
                put(&mut m, "major_group", s(&r.division_id));
                put(&mut m, "major_group_desc", s(&r.division_desc));
                put(&mut m, "industry_group", s(&r.group_id));
                put(&mut m, "industry_group_desc", s(&r.group_desc));
            }
        },
        System::EuNace | System::Isic => match level {
            Level::Section => {}
            Level::Division => put(&mut m, "section_code", r.section_id.clone()),
            Level::Group => {
                put(&mut m, "division_code", s(&r.division_id));
                put(&mut m, "section_code", r.section_id.clone());
            }
            Level::Class => {
                put(&mut m, "group_code", s(&r.group_id));
                put(&mut m, "division_code", s(&r.division_id));
                put(&mut m, "section_code", r.section_id.clone());
            }
        },
        System::Japan => match level {
            Level::Section => {}
            Level::Division => put(&mut m, "division_code", r.section_id.clone()),
            Level::Group => {
                put(&mut m, "major_group_code", s(&r.division_id));
                put(&mut m, "division_code", r.section_id.clone());
            }
            Level::Class => {
                put(&mut m, "group_code", s(&r.group_id));
                put(&mut m, "major_group_code", s(&r.division_id));
                put(&mut m, "division_code", r.section_id.clone());
            }
        },
    }
    // The US description search and every system's description search key by description.
    let key = if by_description { desc } else { id };
    (key, Value::Object(m))
}

/// Shape `rows` exactly as V3 answered (see the module notes for what differs on purpose).
pub fn v3_reply(system: System, level: Level, query: &str, by_description: bool, rows: &[LevelRow]) -> V3Reply {
    let level = if by_description { Level::Class } else { level };
    let (key, word, method, class) = names(system, level, by_description);
    let mut dict = Map::new();
    for r in rows {
        let (k, v) = entry(system, level, by_description, r);
        dict.insert(k, v);
    }
    let total = dict.len();
    let (found, none) = messages(system, level, by_description, word, query);
    let mut data = Map::new();
    data.insert(key.to_string(), Value::Object(dict));
    data.insert("total".to_string(), json!(total));
    V3Reply {
        code: if total == 0 { 404 } else { 200 },
        message: if total == 0 { none } else { found },
        module: format!("{class}-> {method}"),
        data: Value::Object(data),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{SicCatalog, SicSystem};
    use datafusion::arrow::datatypes::{DataType, Field, Schema};
    use datafusion::arrow::record_batch::RecordBatch;
    use datafusion::datasource::MemTable;
    use datafusion::prelude::SessionContext;
    use std::sync::Arc;

    type Row = [&'static str; 8];

    fn table(rows: &[Row]) -> Arc<MemTable> {
        let names = ["section_id", "section_desc", "division_id", "division_desc", "group_id", "group_desc", "class_id", "class_desc"];
        let schema = Arc::new(Schema::new(names.iter().map(|n| Field::new(*n, DataType::LargeUtf8, false)).collect::<Vec<_>>()));
        let cols: Vec<Arc<dyn datafusion::arrow::array::Array>> = (0..8)
            .map(|i| Arc::new(LargeStringArray::from(rows.iter().map(|r| r[i]).collect::<Vec<_>>())) as _)
            .collect();
        Arc::new(MemTable::try_new(schema.clone(), vec![vec![RecordBatch::try_new(schema, cols).unwrap()]]).unwrap())
    }

    /// A catalog with one small table per system, rows taken from what V3 returned for them.
    fn catalog(with_japan: bool) -> SicCatalog {
        let ctx = SessionContext::new();
        let mut systems = Vec::new();
        let mut add = |name: &str, label: &str, rows: &[Row]| {
            ctx.register_table(name, table(rows)).unwrap();
            systems.push(SicSystem { table_name: name.to_string(), source_label: label.to_string() });
        };
        add("sic_data", US, &[
            ["D", "Manufacturing", "35", "Industrial And Commercial Machinery And Computer Equipment", "357", "Computer And Office Equipment", "3571", "Electronic Computers"],
            ["D", "Manufacturing", "35", "Industrial And Commercial Machinery And Computer Equipment", "357", "Computer And Office Equipment", "3572", "Computer Storage Devices"],
            ["E", "Transportation, Communications, Electric, Gas, And Sanitary Services", "40", "Railroad Transportation", "401", "Railroads", "4011", "Railroads, Line-Haul Operating"],
        ]);
        add("sic_data_nace", NACE, &[
            ["A", "AGRICULTURE, FORESTRY AND FISHING", "01", "Crop and animal production", "01.1", "Growing of non-perennial crops", "01.11", "Growing of cereals"],
            ["C", "MANUFACTURING", "25", "Manufacture of fabricated metal products, except machinery and equipment", "25.9", "Manufacture of other fabricated metal products", "25.91", "Manufacture of steel drums and similar containers"],
        ]);
        add("sic_data_isic", ISIC, &[
            ["C", "Manufacturing", "25", "Manufacture of fabricated metal products, except machinery and equipment", "259", "Manufacture of other fabricated metal products; metalworking service activities", "2591", "Forging, pressing, stamping and roll-forming of metal; powder metallurgy"],
        ]);
        if with_japan {
            add("sic_data_japan", JAPAN, &[
                ["E", "MANUFACTURING", "09", "Manufacture of food", "091", "Livestock products", "0911", "Frozen meat and subprimal products"],
                ["E", "MANUFACTURING", "09", "Manufacture of food", "091", "Livestock products", "0912", "Processed meat products"],
            ]);
        }
        SicCatalog { ctx, systems }
    }

    async fn reply(c: &SicCatalog, system: System, level: Level, q: &str, by_desc: bool) -> V3Reply {
        let rows = c.find_in_system(system, level, q, by_desc).await.unwrap().expect("system loaded");
        v3_reply(system, level, q, by_desc, &rows)
    }

    // The expected values below are V3's own answers, captured from production on 2026-10-07.

    #[tokio::test]
    async fn eu_nace_matches_v3() {
        let c = catalog(true);
        let r = reply(&c, System::EuNace, Level::Section, "A", false).await;
        assert_eq!((r.code, r.message.as_str(), r.module.as_str()), (200, "EU SIC section data has been returned for query [A].", "EuSICQueries-> get_section_by_code"));
        assert_eq!(r.data, json!({"sections": {"A": {"description": "AGRICULTURE, FORESTRY AND FISHING"}}, "total": 1}));

        let r = reply(&c, System::EuNace, Level::Group, "25.9", false).await;
        assert_eq!(r.data, json!({"groups": {"25.9": {"description": "Manufacture of other fabricated metal products", "division_code": "25", "section_code": "C"}}, "total": 1}));

        let r = reply(&c, System::EuNace, Level::Class, "25.91", false).await;
        assert_eq!(r.message, "EU SIC class data has been returned for query [25.91].");
        assert_eq!(r.data, json!({"classes": {"25.91": {"description": "Manufacture of steel drums and similar containers", "group_code": "25.9", "division_code": "25", "section_code": "C"}}, "total": 1}));

        let r = reply(&c, System::EuNace, Level::Class, "STEEL", true).await;
        assert_eq!((r.code, r.module.as_str()), (200, "EuSICQueries-> get_class_by_description"));
        assert_eq!(r.message, "EU SIC class data has been returned for description query [STEEL].", "case-insensitive");
        assert_eq!(r.data["classes"]["Manufacture of steel drums and similar containers"], json!({"code": "25.91", "group_code": "25.9", "division_code": "25", "section_code": "C"}));
    }

    #[tokio::test]
    async fn isic_matches_v3_including_its_unprefixed_messages() {
        let c = catalog(true);
        let r = reply(&c, System::Isic, Level::Division, "25", false).await;
        assert_eq!((r.code, r.message.as_str(), r.module.as_str()), (200, "Division data has been returned for query [25].", "InternationalSICQueries-> get_division_by_code"));
        assert_eq!(r.data, json!({"divisions": {"25": {"description": "Manufacture of fabricated metal products, except machinery and equipment", "section_code": "C"}}, "total": 1}));
        let r = reply(&c, System::Isic, Level::Class, "2591", false).await;
        assert_eq!(r.data["classes"]["2591"], json!({"description": "Forging, pressing, stamping and roll-forming of metal; powder metallurgy", "group_code": "259", "division_code": "25", "section_code": "C"}));
        let r = reply(&c, System::Isic, Level::Class, "forging", true).await;
        assert_eq!(r.message, "Class data has been returned for description query [forging].");
    }

    #[tokio::test]
    async fn japan_uses_v3s_level_names() {
        let c = catalog(true);
        // V3 "major_group" is the 2-digit level, whose parent is the lettered "division"
        let r = reply(&c, System::Japan, Level::Division, "09", false).await;
        assert_eq!((r.message.as_str(), r.module.as_str()), ("Japan SIC major group data has been returned for query [09].", "JapanSICQueries-> get_major_group_by_code"));
        assert_eq!(r.data, json!({"major_groups": {"09": {"description": "Manufacture of food", "division_code": "E"}}, "total": 1}));
        let r = reply(&c, System::Japan, Level::Group, "091", false).await;
        assert_eq!(r.data, json!({"groups": {"091": {"description": "Livestock products", "major_group_code": "09", "division_code": "E"}}, "total": 1}));
        let r = reply(&c, System::Japan, Level::Section, "E", false).await;
        assert_eq!(r.data, json!({"divisions": {"E": {"description": "MANUFACTURING"}}, "total": 1}));
        let r = reply(&c, System::Japan, Level::Class, "0911", false).await;
        assert_eq!(r.data["industry_groups"]["0911"], json!({"description": "Frozen meat and subprimal products", "group_code": "091", "major_group_code": "09", "division_code": "E"}));
        let r = reply(&c, System::Japan, Level::Class, "meat", true).await;
        assert_eq!(r.message, "Japan SIC industry group data has been returned for description query [meat].");
        assert_eq!(r.data["total"], 2);
        assert_eq!(r.data["industry_groups"]["Processed meat products"]["code"], "0912");
    }

    #[tokio::test]
    async fn the_us_family_matches_v3() {
        let c = catalog(true);
        let r = reply(&c, System::Us, Level::Class, "3571", false).await;
        assert_eq!((r.message.as_str(), r.module.as_str()), ("SIC data has been returned for query [3571].", "SICQueries-> get_all_sic_by_no"));
        assert_eq!(r.data, json!({"sics": {"3571": {"description": "Electronic Computers", "division": "D", "division_desc": "Manufacturing", "major_group": "35", "major_group_desc": "Industrial And Commercial Machinery And Computer Equipment", "industry_group": "357", "industry_group_desc": "Computer And Office Equipment"}}, "total": 1}));
        let r = reply(&c, System::Us, Level::Division, "35", false).await;
        assert_eq!(r.message, "Major group data has been returned for query [35].");
        assert_eq!(r.data, json!({"major_groups": {"35": {"description": "Industrial And Commercial Machinery And Computer Equipment", "division": "D"}}, "total": 1}));
        let r = reply(&c, System::Us, Level::Group, "357", false).await;
        assert_eq!(r.data, json!({"industry_groups": {"357": {"description": "Computer And Office Equipment", "division": "D", "major_group": "35"}}, "total": 1}));
        let r = reply(&c, System::Us, Level::Section, "E", false).await;
        assert_eq!(r.module, "SICQueries-> get_division_desc_by_id");
        assert_eq!(r.data["division"]["E"]["description"], "Transportation, Communications, Electric, Gas, And Sanitary Services");
        assert_eq!(r.data["division"]["E"]["full_description"], "", "V4 has no division narrative; the key stays so V3 readers do not fail");
        let r = reply(&c, System::Us, Level::Class, "computer", true).await;
        assert_eq!((r.message.as_str(), r.module.as_str()), ("SIC data has been returned for query [computer].", "SICQueries-> get_all_sic_by_name"));
        assert_eq!(r.data["sics"]["Computer Storage Devices"]["code"], "3572");
        assert_eq!(r.data["total"], 2, "\"computer\" is in both Electronic Computers and Computer Storage Devices");
    }

    #[tokio::test]
    async fn no_match_is_a_404_with_v3s_message_and_an_empty_structure() {
        let c = catalog(true);
        let r = reply(&c, System::EuNace, Level::Section, "ZZ", false).await;
        assert_eq!((r.code, r.message.as_str()), (404, "No EU SIC section found for query [ZZ]."));
        assert_eq!(r.data, json!({"sections": {}, "total": 0}));
        assert_eq!(reply(&c, System::Isic, Level::Class, "nothing like this", true).await.message, "No class found for description query [nothing like this].");
        assert_eq!(reply(&c, System::Japan, Level::Section, "ZZ", false).await.message, "No Japan SIC division found for query [ZZ].");
        assert_eq!(reply(&c, System::Us, Level::Class, "9999", false).await.message, "No SIC found for query [9999].");
        assert_eq!(reply(&c, System::Us, Level::Class, "zzz", true).await.message, "No SICs found for query [zzz].");
        assert_eq!(reply(&c, System::Us, Level::Division, "99", false).await.message, "No Major Group found for query [99].");
    }

    #[tokio::test]
    async fn substring_matching_and_quote_safety() {
        let c = catalog(true);
        // V3's LIKE '%q%': "25" is also a substring of "25.91"
        let rows = c.find_in_system(System::EuNace, Level::Class, "25", false).await.unwrap().unwrap();
        assert_eq!(rows.len(), 1);
        // an apostrophe must not break the query
        assert!(c.find_in_system(System::EuNace, Level::Class, "o'brien", true).await.unwrap().unwrap().is_empty());
    }

    #[tokio::test]
    async fn a_system_that_is_not_loaded_is_none() {
        let c = catalog(false);
        assert!(c.find_in_system(System::Japan, Level::Section, "E", false).await.unwrap().is_none());
        assert!(c.find_in_system(System::Isic, Level::Section, "C", false).await.unwrap().is_some());
    }

    #[tokio::test]
    async fn v4_rows_carry_the_level_and_its_parents_only() {
        let c = catalog(true);
        let rows = c.find_in_system(System::Isic, Level::Group, "259", false).await.unwrap().unwrap();
        let j = serde_json::to_value(&rows[0]).unwrap();
        assert!(j.get("group_id").is_some() && j.get("section_id").is_some());
        assert!(j.get("class_id").is_none(), "children are not included");
    }
}
