//! The per-system SIC endpoints (EU NACE, ISIC, Japan SIC) and the V2.0 and `/v2/` aliases -
//! `docs/plans/v4-release-to-staging.md` (New E).
//!
//! Every non-US lookup is served twice, like the US ones: at `/V4.0/...` with V4's shape (a list of matches,
//! each with its parents) and at `/V3.0/...` with V3's exact shape (a dictionary keyed by code with a total, V3's
//! field names, messages and module strings), so an existing V3 integration keeps working. The US SIC
//! `/V3.0/na/sic/...` aliases and the `/V2.0/sic/...` paths use V3's shape too. The `/V2.0/` paths are V3's
//! limited legacy set: V3 served them with the same handlers as their `/V3.0/` twins, and so does V4.
//! The data layer and V3's shapes are in `company_dns_sic::systems`.

use crate::envelope::{envelope, not_found, ok, server_error, ApiEnvelope};
use crate::AppState;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use company_dns_sic::systems::{v3_reply, Level, System};
use serde_json::json;
use std::sync::Arc;

const MODULE: &str = "SicCatalog->find_in_system";

fn level_word(level: Level, by_desc: bool) -> &'static str {
    match (level, by_desc) {
        (_, true) => "class by description",
        (Level::Section, _) => "section",
        (Level::Division, _) => "division",
        (Level::Group, _) => "group",
        (Level::Class, _) => "class",
    }
}

/// V4's shape: a list of matches at the level, each with its parents.
pub async fn v4_lookup(state: &AppState, system: System, level: Level, by_desc: bool, query: &str) -> Response {
    match state.sic.find_in_system(system, level, query, by_desc).await {
        Ok(Some(rows)) if !rows.is_empty() => ok(
            MODULE,
            format!("{} {} matches for [{query}]", rows.len(), level_word(level, by_desc)),
            json!(rows),
        )
        .into_response(),
        Ok(Some(_)) => not_found(
            MODULE,
            format!("No {} {} found for [{query}]", system.label(), level_word(level, by_desc)),
        )
        .into_response(),
        Ok(None) => not_found(MODULE, format!("{} data is not loaded on this server", system.label())).into_response(),
        Err(e) => server_error(MODULE, e.to_string()).into_response(),
    }
}

/// V3's exact shape (see `company_dns_sic::systems` for what differs on purpose).
pub async fn v3_lookup(state: &AppState, system: System, level: Level, by_desc: bool, query: &str) -> Response {
    match state.sic.find_in_system(system, level, query, by_desc).await {
        Ok(Some(rows)) => {
            let r = v3_reply(system, level, query, by_desc, &rows);
            let status = StatusCode::from_u16(r.code).unwrap_or(StatusCode::OK);
            (status, Json(envelope(r.code, r.message, &r.module, r.data))).into_response()
        }
        Ok(None) => not_found(MODULE, format!("{} data is not loaded on this server", system.label())).into_response(),
        Err(e) => server_error(MODULE, e.to_string()).into_response(),
    }
}

/// A V4.0 handler and its V3.0 twin for one lookup.
macro_rules! lookup_pair {
    (
        system: $system:expr, level: $level:expr, by_desc: $by_desc:expr,
        v4: ($v4_fn:ident, $v4_path:literal, $v4_tag:literal),
        v3: ($v3_fn:ident, $v3_path:literal, $v3_tag:literal),
        param: ($param:literal, $param_doc:literal),
        summary: $summary:literal
    ) => {
        #[utoipa::path(
            get,
            path = $v4_path,
            params(($param = String, Path, description = $param_doc)),
            responses(
                (status = 200, description = "Matches at this level, each with its parents (V4 shape: a list)", body = ApiEnvelope),
                (status = 404, description = "No match, or the system is not loaded on this server", body = ApiEnvelope),
                (status = 401, description = "A wrong HTTP Basic credential was sent (an Authorization header that does not match a profile). Calls with no credential are not affected.", body = ApiEnvelope),
                (status = 429, description = "Rate limit exceeded; Retry-After says how many seconds to wait. A self-identifying User-Agent gets a higher limit, and an authenticated profile may have its own quota.", body = ApiEnvelope),
            ),
            tag = $v4_tag,
            summary = $summary
        )]
        pub async fn $v4_fn(State(state): State<Arc<AppState>>, Path(q): Path<String>) -> Response {
            v4_lookup(&state, $system, $level, $by_desc, &q).await
        }

        #[utoipa::path(
            get,
            path = $v3_path,
            params(($param = String, Path, description = $param_doc)),
            responses(
                (status = 200, description = "V3's exact response shape: a dictionary keyed by code (or description) with a total", body = ApiEnvelope),
                (status = 404, description = "No match (V3 answered with an HTML page; V4 answers with this JSON envelope), or the system is not loaded", body = ApiEnvelope),
                (status = 401, description = "A wrong HTTP Basic credential was sent (an Authorization header that does not match a profile). Calls with no credential are not affected.", body = ApiEnvelope),
                (status = 429, description = "Rate limit exceeded; Retry-After says how many seconds to wait. A self-identifying User-Agent gets a higher limit, and an authenticated profile may have its own quota.", body = ApiEnvelope),
            ),
            tag = $v3_tag,
            summary = $summary
        )]
        pub async fn $v3_fn(State(state): State<Arc<AppState>>, Path(q): Path<String>) -> Response {
            v3_lookup(&state, $system, $level, $by_desc, &q).await
        }
    };
}

/// A single legacy-path handler that does what its current-version twin does.
macro_rules! alias {
    (
        $fn:ident, $path:literal, $tag:literal, $summary:literal, ($param:literal, $param_doc:literal),
        |$state:ident, $q:ident| $body:expr
    ) => {
        #[utoipa::path(
            get,
            path = $path,
            params(($param = String, Path, description = $param_doc)),
            responses(
                (status = 200, description = "Identical to the current-version endpoint it aliases", body = ApiEnvelope),
                (status = 404, description = "No match, as for the endpoint it aliases", body = ApiEnvelope),
                (status = 401, description = "A wrong HTTP Basic credential was sent (an Authorization header that does not match a profile). Calls with no credential are not affected.", body = ApiEnvelope),
                (status = 429, description = "Rate limit exceeded; Retry-After says how many seconds to wait. A self-identifying User-Agent gets a higher limit, and an authenticated profile may have its own quota.", body = ApiEnvelope),
            ),
            tag = $tag,
            summary = $summary
        )]
        pub async fn $fn(State($state): State<Arc<AppState>>, Path($q): Path<String>) -> Response {
            $body
        }
    };
}

/// An alias of an endpoint that always answers 200 (the merged firmographics: it falls back to whichever source has the company).
macro_rules! alias_always_200 {
    (
        $fn:ident, $path:literal, $tag:literal, $summary:literal, ($param:literal, $param_doc:literal),
        |$state:ident, $q:ident| $body:expr
    ) => {
        #[utoipa::path(
            get,
            path = $path,
            params(($param = String, Path, description = $param_doc)),
            responses(
                (status = 200, description = "Identical to the current-version endpoint it aliases", body = ApiEnvelope),
                (status = 401, description = "A wrong HTTP Basic credential was sent (an Authorization header that does not match a profile). Calls with no credential are not affected.", body = ApiEnvelope),
                (status = 429, description = "Rate limit exceeded; Retry-After says how many seconds to wait. A self-identifying User-Agent gets a higher limit, and an authenticated profile may have its own quota.", body = ApiEnvelope),
            ),
            tag = $tag,
            summary = $summary
        )]
        pub async fn $fn(State($state): State<Arc<AppState>>, Path($q): Path<String>) -> Response {
            $body
        }
    };
}

// ---- EU NACE: V4.0 (list) and V3.0 (V3 shape) ----
lookup_pair! {
    system: System::EuNace, level: Level::Section, by_desc: false,
    v4: (eu_section, "/V4.0/eu/sic/section/{section_code}", "SIC EU NACE (V4.0)"),
    v3: (eu_section_v3, "/V3.0/eu/sic/section/{section_code}", "SIC EU NACE (V3.0, alias)"),
    param: ("section_code", "NACE section code (A-U)"),
    summary: "EU NACE: section by code"
}
lookup_pair! {
    system: System::EuNace, level: Level::Division, by_desc: false,
    v4: (eu_division, "/V4.0/eu/sic/division/{division_code}", "SIC EU NACE (V4.0)"),
    v3: (eu_division_v3, "/V3.0/eu/sic/division/{division_code}", "SIC EU NACE (V3.0, alias)"),
    param: ("division_code", "NACE division code (2 digits)"),
    summary: "EU NACE: division by code"
}
lookup_pair! {
    system: System::EuNace, level: Level::Group, by_desc: false,
    v4: (eu_group, "/V4.0/eu/sic/group/{group_code}", "SIC EU NACE (V4.0)"),
    v3: (eu_group_v3, "/V3.0/eu/sic/group/{group_code}", "SIC EU NACE (V3.0, alias)"),
    param: ("group_code", "NACE group code (for example 25.9)"),
    summary: "EU NACE: group by code"
}
lookup_pair! {
    system: System::EuNace, level: Level::Class, by_desc: false,
    v4: (eu_class, "/V4.0/eu/sic/class/{class_code}", "SIC EU NACE (V4.0)"),
    v3: (eu_class_v3, "/V3.0/eu/sic/class/{class_code}", "SIC EU NACE (V3.0, alias)"),
    param: ("class_code", "NACE class code (for example 25.91)"),
    summary: "EU NACE: class by code"
}
lookup_pair! {
    system: System::EuNace, level: Level::Class, by_desc: true,
    v4: (eu_description, "/V4.0/eu/sic/description/{class_desc}", "SIC EU NACE (V4.0)"),
    v3: (eu_description_v3, "/V3.0/eu/sic/description/{class_desc}", "SIC EU NACE (V3.0, alias)"),
    param: ("class_desc", "Text to find in a NACE class description"),
    summary: "EU NACE: description by description"
}
// ---- ISIC: V4.0 (list) and V3.0 (V3 shape) ----
lookup_pair! {
    system: System::Isic, level: Level::Section, by_desc: false,
    v4: (international_section, "/V4.0/international/sic/section/{section_code}", "SIC ISIC (V4.0)"),
    v3: (international_section_v3, "/V3.0/international/sic/section/{section_code}", "SIC ISIC (V3.0, alias)"),
    param: ("section_code", "ISIC section code (A-U)"),
    summary: "ISIC: section by code"
}
lookup_pair! {
    system: System::Isic, level: Level::Division, by_desc: false,
    v4: (international_division, "/V4.0/international/sic/division/{division_code}", "SIC ISIC (V4.0)"),
    v3: (international_division_v3, "/V3.0/international/sic/division/{division_code}", "SIC ISIC (V3.0, alias)"),
    param: ("division_code", "ISIC division code (2 digits)"),
    summary: "ISIC: division by code"
}
lookup_pair! {
    system: System::Isic, level: Level::Group, by_desc: false,
    v4: (international_group, "/V4.0/international/sic/group/{group_code}", "SIC ISIC (V4.0)"),
    v3: (international_group_v3, "/V3.0/international/sic/group/{group_code}", "SIC ISIC (V3.0, alias)"),
    param: ("group_code", "ISIC group code (3 digits)"),
    summary: "ISIC: group by code"
}
lookup_pair! {
    system: System::Isic, level: Level::Class, by_desc: false,
    v4: (international_class, "/V4.0/international/sic/class/{class_code}", "SIC ISIC (V4.0)"),
    v3: (international_class_v3, "/V3.0/international/sic/class/{class_code}", "SIC ISIC (V3.0, alias)"),
    param: ("class_code", "ISIC class code (4 digits)"),
    summary: "ISIC: class by code"
}
lookup_pair! {
    system: System::Isic, level: Level::Class, by_desc: true,
    v4: (international_description, "/V4.0/international/sic/description/{class_desc}", "SIC ISIC (V4.0)"),
    v3: (international_description_v3, "/V3.0/international/sic/description/{class_desc}", "SIC ISIC (V3.0, alias)"),
    param: ("class_desc", "Text to find in an ISIC class description"),
    summary: "ISIC: description by description"
}
// ---- Japan: V4.0 (list) and V3.0 (V3 shape) ----
lookup_pair! {
    system: System::Japan, level: Level::Section, by_desc: false,
    v4: (japan_division, "/V4.0/japan/sic/division/{division_code}", "SIC Japan (V4.0)"),
    v3: (japan_division_v3, "/V3.0/japan/sic/division/{division_code}", "SIC Japan (V3.0, alias)"),
    param: ("division_code", "Japan SIC division code (A-T)"),
    summary: "Japan: division by code"
}
lookup_pair! {
    system: System::Japan, level: Level::Division, by_desc: false,
    v4: (japan_major_group, "/V4.0/japan/sic/major_group/{major_group_code}", "SIC Japan (V4.0)"),
    v3: (japan_major_group_v3, "/V3.0/japan/sic/major_group/{major_group_code}", "SIC Japan (V3.0, alias)"),
    param: ("major_group_code", "Japan SIC major group code (2 digits)"),
    summary: "Japan: major group by code"
}
lookup_pair! {
    system: System::Japan, level: Level::Group, by_desc: false,
    v4: (japan_group, "/V4.0/japan/sic/group/{group_code}", "SIC Japan (V4.0)"),
    v3: (japan_group_v3, "/V3.0/japan/sic/group/{group_code}", "SIC Japan (V3.0, alias)"),
    param: ("group_code", "Japan SIC group code (3 digits)"),
    summary: "Japan: group by code"
}
lookup_pair! {
    system: System::Japan, level: Level::Class, by_desc: false,
    v4: (japan_industry_group, "/V4.0/japan/sic/industry_group/{industry_code}", "SIC Japan (V4.0)"),
    v3: (japan_industry_group_v3, "/V3.0/japan/sic/industry_group/{industry_code}", "SIC Japan (V3.0, alias)"),
    param: ("industry_code", "Japan SIC industry group code (4 digits)"),
    summary: "Japan: industry group by code"
}
lookup_pair! {
    system: System::Japan, level: Level::Class, by_desc: true,
    v4: (japan_description, "/V4.0/japan/sic/description/{industry_desc}", "SIC Japan (V4.0)"),
    v3: (japan_description_v3, "/V3.0/japan/sic/description/{industry_desc}", "SIC Japan (V3.0, alias)"),
    param: ("industry_desc", "Text to find in a Japan SIC industry group description"),
    summary: "Japan: description by description"
}
// ---- V2.0: V3's limited legacy set, answered exactly like the /V3.0/ twins ----
alias!(sic_description_v2, "/V2.0/sic/description/{sic_desc}", "SIC (V2.0, alias)", "US SIC by description", ("sic_desc", "SIC description search term"),
    |state, q| v3_lookup(&state, System::Us, Level::Class, true, &q).await);
alias!(sic_code_v2, "/V2.0/sic/code/{sic_code}", "SIC (V2.0, alias)", "US SIC by code", ("sic_code", "SIC numeric code"),
    |state, q| v3_lookup(&state, System::Us, Level::Class, false, &q).await);
alias!(sic_division_v2, "/V2.0/sic/division/{division_code}", "SIC (V2.0, alias)", "US SIC division by code", ("division_code", "SIC division code"),
    |state, q| v3_lookup(&state, System::Us, Level::Section, false, &q).await);
alias!(sic_industry_v2, "/V2.0/sic/industry/{industry_code}", "SIC (V2.0, alias)", "US SIC industry group by code", ("industry_code", "SIC industry-group code"),
    |state, q| v3_lookup(&state, System::Us, Level::Group, false, &q).await);
alias!(sic_major_v2, "/V2.0/sic/major/{major_code}", "SIC (V2.0, alias)", "US SIC major group by code", ("major_code", "SIC major-group code"),
    |state, q| v3_lookup(&state, System::Us, Level::Division, false, &q).await);
alias!(edgar_ciks_v2, "/V2.0/companies/edgar/ciks/{company_name}", "EDGAR (V2.0, alias)", "CIK numbers for a company name", ("company_name", "Company name"),
    |state, q| crate::v3_edgar::ciks(&state, &q).await);
alias!(edgar_detail_v2, "/V2.0/companies/edgar/detail/{company_name}", "EDGAR (V2.0, alias)", "Detailed EDGAR company information", ("company_name", "Company name"),
    |state, q| crate::v3_edgar::detail(&state, &q).await);
alias!(edgar_summary_v2, "/V2.0/companies/edgar/summary/{company_name}", "EDGAR (V2.0, alias)", "EDGAR company summary", ("company_name", "Company name"),
    |state, q| crate::v3_edgar::summary(&state, &q).await);
alias!(edgar_firmographics_v2, "/V2.0/company/edgar/firmographics/{cik_no}", "EDGAR (V2.0, alias)", "EDGAR firmographics by CIK", ("cik_no", "CIK number"),
    |state, q| crate::v3_edgar::firmographics(&state, &q).await);
alias!(wikipedia_firmographics_v2_legacy, "/V2.0/company/wikipedia/firmographics/{company_name}", "Wikipedia (V2.0, alias)", "Firmographics from Wikipedia", ("company_name", "Company name"),
    |state, q| crate::wikipedia_firmographics_v3_impl(&state, &q).await.into_response());
alias_always_200!(merged_firmographics_v2_legacy, "/V2.0/company/merged/firmographics/{company_name}", "Merged (V2.0, alias)", "Merged firmographics from all sources", ("company_name", "Company name"),
    |state, q| crate::merged_firmographics_impl(&state, &q).await.into_response());
// ---- the explicit /v2/ URLs: V3 documents them as "same as default" ----
alias!(wikipedia_firmographics_v2_url, "/V3.0/global/company/wikipedia/v2/firmographics/{company_name}", "Wikipedia (V3.0, alias)", "Firmographics from Wikipedia (the v2 backend, same as the default path)", ("company_name", "Company name"),
    |state, q| crate::wikipedia_firmographics_v3_impl(&state, &q).await.into_response());
alias_always_200!(merged_firmographics_v2_url, "/V3.0/global/company/merged/v2/firmographics/{company_name}", "Merged (V3.0, alias)", "Merged firmographics (the v2 Wikipedia backend, same as the default path)", ("company_name", "Company name"),
    |state, q| crate::merged_firmographics_impl(&state, &q).await.into_response());
