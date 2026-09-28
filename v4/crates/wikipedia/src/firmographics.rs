//! Port of `lib/wikipedia_v2.py`'s `get_firmographics` field-construction
//! logic (lines 458-511) - the transforms applied on top of the raw
//! infobox map + Wikidata claims this spike's `infobox`/`fetch_wikidata`
//! already produce, to reach V3's actual firmographics field shape
//! (`name`, `industry`, `country`, `city`, `website`, `isin`, `cik`,
//! `exchanges`, `tickers`, `type`, `description`, `wikipediaURL`).
//!
//! **Corrected by the side-by-side diff against V3's live output**
//! (README, "Side-by-side diff"): wptools' `_build_wikidata_dict`
//! collapses a single-value claim to a *bare string* and only a
//! multi-value claim to a list (`if len(vals) == 1: claim = ilabel else:
//! claim.append(ilabel)`), and `get_firmographics` doesn't apply the
//! same `isinstance(..., list)` check consistently to every field:
//! `industry`/`exchanges`/`website` always end up as a list regardless
//! (their `if not isinstance(...)` branch explicitly re-wraps in `[...]`),
//! but `country` and `cik` do NOT - `country`'s non-list branch keeps it
//! bare, and `cik` has no isinstance check at all, just a direct
//! passthrough of whatever shape the claim naturally collapsed to. A
//! live diff for IBM/Apple/Tesla caught this: V3 actually returns
//! `"country": "United States"` and `"cik": "0000051143"` as bare
//! strings, not 1-element lists - an earlier version of this port forced
//! every Wikidata-sourced field into a list, which was a real V3-parity
//! bug, not a harmless normalization as first assumed.

use regex::Regex;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::LazyLock;

const UKN: &str = "Unknown";

static RE_BRACKETS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\[\[|\]\]").unwrap());
static RE_PARENS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\s*\(\S+\)$").unwrap());
static RE_PIPES: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\|").unwrap());
static RE_BRACES: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\{\{.+?\|.+?\}\}").unwrap());
static RE_BR: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<br>").unwrap());

/// Port of wptools' `_get_item`: strip the character set implied by
/// Python's `str.strip(rules)` call (a *character set*, not a regex,
/// despite `rules` looking like one - e.g. `r'[\[\]]'` strips any of
/// `[`, `\`, `]` from both ends) from the first matching variant field,
/// then split on `|` and take `idx` if a pipe is present.
fn get_item(
    obj: &HashMap<String, String>,
    variants: &[&str],
    strip_chars: &[char],
    idx: usize,
) -> String {
    for variant in variants {
        if let Some(raw) = obj.get(*variant) {
            let tmp = raw.trim_matches(|c| strip_chars.contains(&c));
            if RE_PIPES.is_match(tmp) {
                let parts: Vec<&str> = RE_PIPES.split(tmp).collect();
                return parts.get(idx).unwrap_or(&tmp).to_string();
            }
            return tmp.to_string();
        }
    }
    UKN.to_string()
}

/// Port of wptools' `_transform_isin`.
fn transform_isin(isin: &str) -> String {
    if isin.contains("ISIN") {
        let Some(m) = RE_BRACES.find_iter(isin.trim()).last() else {
            return UKN.to_string();
        };
        let tmp = m.as_str().trim_matches(|c| c == '{' || c == '}');
        return tmp.rsplit('|').next().unwrap_or(tmp).to_string();
    }
    isin.trim_matches(|c| c == '{' || c == '}').to_string()
}

/// Port of wptools' `_transform_stock_ticker`.
fn transform_stock_ticker(traded_as: &str) -> [String; 2] {
    let Some(m) = RE_BRACES.find_iter(traded_as.trim()).last() else {
        return [UKN.to_string(), UKN.to_string()];
    };
    let tmp = m.as_str().trim_matches(|c| c == '{' || c == '}');
    let parts: Vec<&str> = RE_PIPES.split(tmp).collect();
    if parts.len() >= 2 {
        [parts[0].to_string(), parts[1].to_string()]
    } else {
        [UKN.to_string(), UKN.to_string()]
    }
}

fn strip_parens_list(vals: &[String]) -> Vec<String> {
    vals.iter()
        .map(|v| RE_PARENS.replace(v, "").trim().to_string())
        .collect()
}

/// A raw Wikidata claim `Value` is always either `String` (single value,
/// wptools' own collapse rule) or `Array` (multiple values) - never
/// anything else, since `client::fetch_wikidata` only ever produces one
/// of those two shapes. Used by the fields that always render as a list
/// regardless of the claim's own shape (`industry`/`exchanges`/`website`).
fn as_string_list(v: &Value) -> Vec<String> {
    match v {
        Value::String(s) => vec![s.clone()],
        Value::Array(a) => a
            .iter()
            .filter_map(|x| x.as_str())
            .map(String::from)
            .collect(),
        _ => vec![],
    }
}

pub struct RawInputs<'a> {
    pub infobox: Option<&'a HashMap<String, String>>,
    pub wikidata: &'a HashMap<String, Value>,
    pub extract: Option<&'a str>,
    pub url: Option<&'a str>,
}

/// Port of `get_firmographics`'s field-construction section
/// (`lib/wikipedia_v2.py` lines 458-511) - builds V3's actual
/// firmographics shape from the raw infobox/Wikidata inputs this
/// spike's HTTP layer already fetches and parses.
pub fn build_firmographics(inputs: RawInputs) -> Value {
    let empty_map = HashMap::new();
    let company_info = inputs.infobox.unwrap_or(&empty_map);
    let wikidata = inputs.wikidata;

    let mut out = serde_json::Map::new();

    if let Some(extract) = inputs.extract {
        out.insert(
            "description".into(),
            json!(extract.replace('\n', " ").replace("**", "")),
        );
    }
    out.insert("wikipediaURL".into(), json!(inputs.url));

    if let Some(raw_type) = company_info.get("type") {
        let company_type = RE_BRACKETS.replace_all(raw_type, "");
        let company_type = if RE_PIPES.is_match(&company_type) {
            RE_PIPES
                .split(&company_type)
                .next()
                .unwrap_or("")
                .trim()
                .to_string()
        } else {
            company_type.to_string()
        };
        let final_type = if company_type.contains('(') {
            company_type
                .split('(')
                .next()
                .unwrap_or("")
                .trim()
                .to_string()
        } else {
            company_type
        };
        out.insert("type".into(), json!(final_type));
    } else {
        out.insert("type".into(), json!("Private Company (Assumed)"));
    }

    // industry: always a list, regardless of the claim's own shape -
    // Python's non-list branch explicitly re-wraps in `[...]`.
    let industry = wikidata
        .get("industry (P452)")
        .map(as_string_list)
        .unwrap_or_else(|| vec![UKN.to_string()]);
    out.insert("industry".into(), json!(strip_parens_list(&industry)));

    out.insert(
        "name".into(),
        json!(company_info
            .get("name")
            .cloned()
            .unwrap_or_else(|| UKN.to_string())),
    );

    // country: stays whatever shape the claim naturally collapsed to -
    // bare string for a single value, list for multiple. Python's
    // non-list branch does NOT re-wrap (unlike industry above).
    let country_val = wikidata.get("country (P17)").cloned().unwrap_or_else(|| {
        Value::String(get_item(
            company_info,
            &["location_country", "hq_location_country"],
            &['[', '\\', ']'],
            0,
        ))
    });
    let country_out = match &country_val {
        Value::Array(_) => json!(strip_parens_list(&as_string_list(&country_val))),
        Value::String(s) => json!(RE_PARENS.replace(s, "").trim().to_string()),
        _ => country_val.clone(),
    };
    out.insert("country".into(), country_out);

    let mut city = get_item(
        company_info,
        &["location_city", "hq_location_city", "location"],
        &['\\', '[', ']'],
        0,
    );
    city = RE_BRACKETS.replace_all(&city, "").to_string();
    city = RE_BR.replace_all(&city, ", ").to_string();
    out.insert("city".into(), json!(city));

    // website: always a list, same as industry above.
    let website = wikidata
        .get("official website (P856)")
        .map(as_string_list)
        .unwrap_or_else(|| {
            vec![get_item(
                company_info,
                &["website", "homepage", "url"],
                &['[', '\\', '{', '}', ']'],
                1,
            )]
        });
    out.insert("website".into(), json!(website));

    let isin = company_info
        .get("ISIN")
        .map(|s| transform_isin(s))
        .unwrap_or_else(|| UKN.to_string());
    out.insert("isin".into(), json!(isin));

    // cik: no isinstance check in Python at all - a direct passthrough
    // of whatever shape the claim collapsed to (always a bare string in
    // practice, since a company has exactly one CIK, but not forced).
    out.insert(
        "cik".into(),
        wikidata
            .get("Central Index Key (P5531)")
            .cloned()
            .unwrap_or_else(|| json!(UKN)),
    );

    // exchanges: always a list, same rule as industry/website.
    let exchanges = wikidata
        .get("stock exchange (P414)")
        .map(as_string_list)
        .unwrap_or_else(|| vec![UKN.to_string()]);
    out.insert("exchanges".into(), json!(strip_parens_list(&exchanges)));

    if let Some(traded_as) = company_info.get("traded_as") {
        out.insert("tickers".into(), json!(transform_stock_ticker(traded_as)));
    }

    Value::Object(out)
}
