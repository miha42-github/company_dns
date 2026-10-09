//! V3's exact answers for the EDGAR routes on the `/V3.0/` and `/V2.0/` paths -
//! `docs/plans/v4-release-to-staging.md` (step 3 finding, decision Q14).
//!
//! V4's own shapes (on `/V4.0/`) stay as they are; these three routes answer the way V3 does so an existing V3 integration keeps
//! working:
//!
//! - `ciks`: `{"companies": {name: cik-as-a-string}, "totalCompanies": n}` (V4 returns `{name: cik-as-a-number}`).
//! - `detail`: each company is V3's whole firmographics response (`code`, `message`, `module`, `data`, `dependencies`) with its
//!   `forms` beside it (V4 flattens the firmographics into the company).
//! - firmographics by CIK: V3 adds the SIC hierarchy (`division`, `divisionDescription`, `majorGroup`, `majorGroupDescription`,
//!   `industryGroup`, `industryGroupDescription`) from its US SIC tables, and, when the SIC code is found there, uses that
//!   table's description as `sicDescription`. V4 does the same from its own US SIC data.
//!
//! `summary` already matched V3's shape and is unchanged. The merged route is still a known difference (decision recorded in the plan).

use crate::envelope::{envelope, not_found, server_error};
use crate::AppState;
use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use company_dns_sic::systems::{Level, LevelRow, System};
use serde_json::{json, Map, Value};
use std::sync::Arc;

/// V3's placeholder when a value cannot be found.
const UKN: &str = "Unknown";

fn reply(code: u16, message: String, module: &str, data: Value) -> Response {
    (StatusCode::from_u16(code).unwrap_or(StatusCode::OK), Json(envelope(code, message, module, data))).into_response()
}

const NOT_LOADED: &str = "EDGAR catalog not loaded - run `cargo run --bin ingest-edgar` first";

/// `GET .../edgar/ciks/{name}`
pub async fn ciks(state: &AppState, name: &str) -> Response {
    const MODULE: &str = "EdgarQueries-> get_all_ciks";
    let Some(catalog) = &state.edgar_catalog else {
        return server_error(MODULE, NOT_LOADED).into_response();
    };
    let matches = match catalog.find_by_name(name).await {
        Ok(m) => m,
        Err(e) => return server_error(MODULE, e.to_string()).into_response(),
    };
    let companies: std::collections::BTreeMap<String, String> = matches.iter().map(|m| (m.company_name.clone(), m.cik.to_string())).collect();
    let total = companies.len();
    let data = json!({"companies": companies, "totalCompanies": total});
    if total == 0 {
        reply(404, format!("No company CIK found for query [{name}]."), MODULE, data)
    } else {
        reply(200, format!("Company CIK data has been returned for query [{name}]."), MODULE, data)
    }
}

/// `GET .../edgar/summary/{name}`: V3's detail without the live firmographics (`{cik, companyName, forms}` per company), under
/// V3's `get_all_details` message and module.
pub async fn summary(state: &AppState, name: &str) -> Response {
    const MODULE: &str = "EdgarQueries-> get_all_details";
    let Some(catalog) = &state.edgar_catalog else {
        return server_error(MODULE, NOT_LOADED).into_response();
    };
    let groups = match catalog.find_grouped_by_name(name).await {
        Ok(g) => g,
        Err(e) => return server_error(MODULE, e.to_string()).into_response(),
    };
    if groups.is_empty() {
        return reply(404, format!("No company found for query [{name}]."), MODULE, json!({"companies": {}, "totalCompanies": 0}));
    }
    let mut companies = Map::new();
    for g in &groups {
        companies.insert(g.company_name.clone(), json!({"cik": g.cik.to_string(), "companyName": g.company_name, "forms": g.forms}));
    }
    let total = companies.len();
    reply(200, format!("Company data has been returned for query [{name}]."), MODULE, json!({"companies": companies, "totalCompanies": total}))
}

/// `GET .../edgar/detail/{name}`
pub async fn detail(state: &Arc<AppState>, name: &str) -> Response {
    const MODULE: &str = "EdgarQueries-> get_all_details";
    let Some(catalog) = &state.edgar_catalog else {
        return server_error(MODULE, NOT_LOADED).into_response();
    };
    let groups = match catalog.find_grouped_by_name(name).await {
        Ok(g) => g,
        Err(e) => return server_error(MODULE, e.to_string()).into_response(),
    };
    if groups.is_empty() {
        return reply(404, format!("No company found for query [{name}]."), MODULE, json!({"companies": {}, "totalCompanies": 0}));
    }
    let mut companies = Map::new();
    for g in &groups {
        let mut info = match state.edgar_client.get_firmographics(g.cik).await {
            Ok(fg) => {
                let mut data = (*fg).clone();
                add_sic_hierarchy(state, &mut data).await;
                envelope(200, format!("Company data has been returned for query [{}].", g.cik), "EdgarQueries-> get_firmographics", data)
            }
            // a catalog match with no live firmographics still gets an entry, as V4's own detail does
            Err(_) => json!({"cik": g.cik.to_string(), "companyName": g.company_name}),
        };
        info["forms"] = json!(g.forms);
        companies.insert(g.company_name.clone(), info);
    }
    let total = companies.len();
    reply(200, format!("Company data has been returned for query [{name}]."), MODULE, json!({"companies": companies, "totalCompanies": total}))
}

/// `GET .../edgar/firmographics/{cik}`
pub async fn firmographics(state: &AppState, cik_no: &str) -> Response {
    const MODULE: &str = "EdgarQueries-> get_firmographics";
    let cik: u64 = match cik_no.trim_start_matches('0').parse() {
        Ok(c) => c,
        Err(_) => return server_error(MODULE, format!("invalid CIK: [{cik_no}]")).into_response(),
    };
    match state.edgar_client.get_firmographics(cik).await {
        Ok(fg) => {
            let mut data = (*fg).clone();
            add_sic_hierarchy(state, &mut data).await;
            reply(200, format!("Company data has been returned for query [{cik_no}]."), MODULE, data)
        }
        Err(e) => not_found(MODULE, format!("No firmographics for CIK [{cik_no}]: {e}")).into_response(),
    }
}

/// The US SIC row at `level` whose code is exactly `code`, if any.
async fn find(state: &AppState, level: Level, code: &str) -> Option<LevelRow> {
    if code.is_empty() {
        return None;
    }
    let rows = state.sic.find_in_system(System::Us, level, code, false).await.ok().flatten()?;
    rows.into_iter().find(|r| match level {
        Level::Section => r.section_id == code,
        Level::Division => r.division_id.as_deref() == Some(code),
        Level::Group => r.group_id.as_deref() == Some(code),
        Level::Class => r.class_id.as_deref() == Some(code),
    })
}

async fn add_sic_hierarchy(state: &AppState, firmographics: &mut Value) {
    let sic = firmographics.get("sic").and_then(Value::as_str).unwrap_or("").trim().to_string();
    let class = find(state, Level::Class, &sic).await;
    let (group, major) = if class.is_some() {
        (None, None)
    } else {
        (find(state, Level::Group, prefix(&sic, 3)).await, find(state, Level::Division, prefix(&sic, 2)).await)
    };
    if let Some(obj) = firmographics.as_object_mut() {
        for (k, v) in sic_fields(&sic, class.as_ref(), group.as_ref(), major.as_ref()) {
            obj.insert(k.to_string(), Value::String(v));
        }
    }
}

fn prefix(s: &str, n: usize) -> &str {
    s.get(..n).unwrap_or(s)
}

fn desc(v: &Option<String>) -> String {
    v.clone().unwrap_or_else(|| UKN.to_string())
}

/// V3's SIC enrichment, as a pure function of the rows found. With the full SIC code found, everything comes from that row
/// (and its `sicDescription` replaces the SEC's). Otherwise V3 falls back to the first three digits for the industry group and
/// the first two for the major group, takes the division from the major group, and says "Unknown" where it finds nothing.
pub fn sic_fields(sic: &str, class: Option<&LevelRow>, group: Option<&LevelRow>, major: Option<&LevelRow>) -> Vec<(&'static str, String)> {
    if let Some(c) = class {
        return vec![
            ("sicDescription", desc(&c.class_desc)),
            ("division", c.section_id.clone()),
            ("divisionDescription", c.section_desc.clone()),
            ("majorGroup", desc(&c.division_id)),
            ("majorGroupDescription", desc(&c.division_desc)),
            ("industryGroup", desc(&c.group_id)),
            ("industryGroupDescription", desc(&c.group_desc)),
        ];
    }
    let mut out = vec![
        ("industryGroup", prefix(sic, 3).to_string()),
        ("industryGroupDescription", group.map(|g| desc(&g.group_desc)).unwrap_or_else(|| UKN.to_string())),
        ("majorGroup", prefix(sic, 2).to_string()),
        ("majorGroupDescription", major.map(|m| desc(&m.division_desc)).unwrap_or_else(|| UKN.to_string())),
    ];
    match major {
        Some(m) => {
            out.push(("division", m.section_id.clone()));
            out.push(("divisionDescription", m.section_desc.clone()));
        }
        None => {
            out.push(("division", UKN.to_string()));
            out.push(("divisionDescription", UKN.to_string()));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row() -> LevelRow {
        LevelRow {
            section_id: "D".into(),
            section_desc: "Manufacturing".into(),
            division_id: Some("35".into()),
            division_desc: Some("Industrial And Commercial Machinery And Computer Equipment".into()),
            group_id: Some("357".into()),
            group_desc: Some("Computer And Office Equipment".into()),
            class_id: Some("3571".into()),
            class_desc: Some("Electronic Computers".into()),
            section_full_desc: None,
        }
    }

    fn get<'a>(fields: &'a [(&'static str, String)], k: &str) -> &'a str {
        &fields.iter().find(|(n, _)| *n == k).unwrap_or_else(|| panic!("no {k}")).1
    }

    #[test]
    fn a_found_sic_code_gives_v3s_values_for_apple() {
        // V3's own answer for CIK 320193 (sic 3571), captured from production on 2026-10-07
        let f = sic_fields("3571", Some(&row()), None, None);
        assert_eq!(get(&f, "sicDescription"), "Electronic Computers");
        assert_eq!((get(&f, "division"), get(&f, "divisionDescription")), ("D", "Manufacturing"));
        assert_eq!(get(&f, "majorGroup"), "35");
        assert_eq!(get(&f, "majorGroupDescription"), "Industrial And Commercial Machinery And Computer Equipment");
        assert_eq!((get(&f, "industryGroup"), get(&f, "industryGroupDescription")), ("357", "Computer And Office Equipment"));
        assert_eq!(f.len(), 7);
    }

    #[test]
    fn an_unknown_code_falls_back_to_its_prefixes() {
        let f = sic_fields("3579", None, Some(&row()), Some(&row()));
        assert_eq!((get(&f, "industryGroup"), get(&f, "industryGroupDescription")), ("357", "Computer And Office Equipment"));
        assert_eq!(get(&f, "majorGroup"), "35");
        assert_eq!((get(&f, "division"), get(&f, "divisionDescription")), ("D", "Manufacturing"));
        assert!(f.iter().all(|(k, _)| *k != "sicDescription"), "the SEC's description is kept when the code is not in the table");
    }

    #[test]
    fn nothing_found_is_unknown() {
        let f = sic_fields("9", None, None, None);
        assert_eq!((get(&f, "industryGroup"), get(&f, "majorGroup")), ("9", "9"), "a short code is used as it is");
        for k in ["industryGroupDescription", "majorGroupDescription", "division", "divisionDescription"] {
            assert_eq!(get(&f, k), "Unknown", "{k}");
        }
    }

    #[test]
    fn prefix_never_panics() {
        assert_eq!((prefix("3571", 3), prefix("35", 3), prefix("", 2)), ("357", "35", ""));
    }
}
