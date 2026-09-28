//! The real Wikipedia/Wikidata HTTP client - promoted from
//! `experiments/wikipedia-spike/src/main.rs` (`docs/plans/
//! v4-server-prototype.md` sec8.1). Reproduces the request-layer fixes
//! `lib/wikipedia_v2.py`'s docstring credits for beating wptools on
//! speed and leanness (narrowed field requests, one targeted Wikidata
//! labels request, a real identifying User-Agent, `maxlag`/429/503/
//! Retry-After handling), plus real work the spike did beyond a straight
//! port: an infobox-presence gate (a page existing isn't enough to
//! accept it as a company match - see `resolve_candidate`) and a
//! canonical-title fix for Wikidata lookups after a Wikipedia-side
//! redirect (see `QueryData::canonical_title`).
//!
//! Deliberately NOT ported here: `resolve_title`, the spike's
//! MediaWiki-full-text-search-based bare-name resolver (60% success on
//! its 5 test cases). It answers a different, narrower question (a name
//! phrased completely unlike its Wikipedia title, not just missing a
//! corporate suffix) that's explicitly a V4-only feature question, not
//! part of V3 parity - see that spike's README "Recommended next step".

use crate::firmographics::{self, RawInputs};
use crate::infobox;
use regex::Regex;
use std::collections::HashMap;
use std::time::Duration;

const WIKIPEDIA_API: &str = "https://en.wikipedia.org/w/api.php";
const WIKIDATA_API: &str = "https://www.wikidata.org/w/api.php";

// MediaWiki API etiquette: ask the server to decline rather than serve us
// (and worsen replication lag) past this many seconds -
// https://www.mediawiki.org/wiki/Manual:Maxlag_parameter. lib/wikipedia_v2.py
// uses the same value, same reasoning.
const MAXLAG: &str = "5";

// The only Wikidata properties lib/wikipedia_v2.py (and lib/wikipedia.py
// before it) ever reads - narrowing to just these is item 6 Finding 4's
// dominant fix (308 entities / 7 requests / ~2.8s -> 13 entities / 1
// request / ~0.3s for IBM, per that module's docstring).
const WANTED_WIKIDATA_PROPS: &[&str] = &["P452", "P17", "P856", "P5531", "P414"];

/// V3's exact corporate-suffix hint heuristic
/// (`lib/wikipedia_v2.py`/`lib/wikipedia.py`'s identical `lookup_error`
/// dict): three straightforward suffix guesses, tried in this order.
/// Confirmed (2026-09-28) that V3's `message` text carrying this hint is
/// computed but never actually reaches an HTTP client - `company_dns.py`'s
/// custom 404 handler unconditionally serves a static HTML error page for
/// any 404 status, discarding `HTTPException.detail` (which is exactly
/// this hint text) regardless of its contents. This client does two
/// things V3 doesn't: surfaces the hint as real message text (V4's
/// `not_found` responses are always JSON, never HTML, so there's no
/// equivalent swallowing bug to reproduce), and goes one step further by
/// actually issuing the suggested REST calls itself, so a caller gets
/// the resolved company back directly instead of a suggestion to retry.
const SUFFIX_HINTS: &[&str] = &[" Inc.", " Corp.", " Corporation"];

/// Byte-for-byte the same message text `lib/wikipedia_v2.py`'s
/// `lookup_error['message']` builds - kept as a real V3-parity string,
/// not paraphrased, in case a caller depends on its exact wording.
pub(crate) fn hint_message(query: &str) -> String {
    format!(
        "Unable to find a company by the name [{query}]. Maybe you should try an alternative \
         structure like [{query} Inc.,{query} Corp., or {query} Corporation]."
    )
}

/// GET with maxlag baked into every request and basic 429/503 handling
/// respecting Retry-After - direct port of lib/wikipedia_v2.py's
/// `_get_with_backoff`. wptools has neither of these (that module's
/// docstring, Finding 5).
async fn get_with_backoff(
    client: &reqwest::Client,
    url: &str,
    mut params: Vec<(&str, String)>,
) -> anyhow::Result<serde_json::Value> {
    params.push(("maxlag", MAXLAG.to_string()));
    let max_retries = 2;
    let mut last_status = None;
    for attempt in 0..=max_retries {
        let resp = client.get(url).query(&params).send().await?;
        let status = resp.status();
        if (status.as_u16() == 429 || status.as_u16() == 503) && attempt < max_retries {
            let retry_after = resp
                .headers()
                .get("Retry-After")
                .and_then(|v| v.to_str().ok())
                .and_then(|s| s.parse::<u64>().ok())
                .unwrap_or(2u64.pow(attempt as u32));
            tokio::time::sleep(Duration::from_secs(retry_after)).await;
            last_status = Some(status);
            continue;
        }
        let body = resp.error_for_status()?.json::<serde_json::Value>().await?;
        return Ok(body);
    }
    anyhow::bail!("exhausted retries, last status: {:?}", last_status)
}

/// Narrowed action=parse request - only `parsetree`, not wptools' full
/// default prop set (also fetches rendered HTML, raw wikitext, interwiki
/// links, display title - none of it used downstream). lib/wikipedia_v2.py
/// measured this cutting the parse response from ~937KB to ~178KB for IBM.
async fn fetch_infobox(
    client: &reqwest::Client,
    wikipedia_api: &str,
    title: &str,
) -> anyhow::Result<Option<HashMap<String, String>>> {
    let data = get_with_backoff(
        client,
        wikipedia_api,
        vec![
            ("action", "parse".into()),
            ("format", "json".into()),
            ("formatversion", "2".into()),
            ("contentmodel", "text".into()),
            ("disableeditsection", "".into()),
            ("disablelimitreport", "".into()),
            ("disabletoc", "".into()),
            ("redirects", "1".into()),
            ("page", title.into()),
            ("prop", "parsetree".into()),
        ],
    )
    .await?;

    if data.get("error").is_some() {
        return Ok(None);
    }
    let Some(parsetree) = data
        .get("parse")
        .and_then(|p| p.get("parsetree"))
        .and_then(|s| s.as_str())
    else {
        return Ok(None);
    };

    Ok(infobox::get_infobox_map(parsetree))
}

struct QueryData {
    extract: Option<String>,
    url: Option<String>,
    /// The canonical title MediaWiki resolved `titles=` to, after
    /// following any redirect (`redirects=1`) - NOT necessarily the same
    /// string that was requested. Matters because Wikidata's own
    /// `sites=enwiki&titles=` sitelink lookup does NOT follow Wikipedia-
    /// side redirects the way `action=query` does: querying Wikidata for
    /// a redirect alias like "Meta Inc." (which Wikipedia happily
    /// resolves to "Meta Platforms") comes back `"missing"` there, since
    /// Wikidata only indexes the canonical title as a sitelink. Found
    /// live testing the suffix-hint mechanism on "Meta": it correctly
    /// resolved to "Meta Inc." (a real redirect), got the right
    /// description/name/website from the Wikipedia-side infobox, but
    /// `cik`/`industry`/`exchanges` all came back "Unknown" because
    /// `fetch_wikidata` was called with the redirect alias instead of
    /// the canonical title.
    canonical_title: Option<String>,
}

/// Narrowed action=query request - only `extracts|info`, matching
/// lib/wikipedia_v2.py's `_fetch_query`. Takes `wikipedia_api` as a
/// parameter (rather than reading a hardcoded constant) so
/// `resolve_candidate`'s suffix-hint mechanism can be tested
/// deterministically against a mock server instead of only against
/// Wikipedia's live redirect graph - see the `tests` module below.
async fn fetch_query(
    client: &reqwest::Client,
    wikipedia_api: &str,
    title: &str,
) -> anyhow::Result<Option<QueryData>> {
    let data = get_with_backoff(
        client,
        wikipedia_api,
        vec![
            ("action", "query".into()),
            ("exintro", "".into()),
            ("format", "json".into()),
            ("formatversion", "2".into()),
            ("inprop", "url".into()),
            ("prop", "extracts|info".into()),
            ("redirects", "1".into()),
            ("titles", title.into()),
        ],
    )
    .await?;

    let pages = data
        .get("query")
        .and_then(|q| q.get("pages"))
        .and_then(|p| p.as_array())
        .cloned()
        .unwrap_or_default();
    let Some(page) = pages.first() else {
        return Ok(None);
    };
    if page.get("missing").is_some() {
        return Ok(None);
    }
    // lib/wikipedia_v2.py's `_fetch_query` runs the raw HTML `extract`
    // through Python's `html2text` before returning it - without it,
    // `description` still has raw `<p class="mw-empty-elt">` tags in
    // it. A large wrap width avoids hard line-wrapping (the final
    // `.replace('\n', " ")` in `firmographics::build_firmographics`
    // would collapse it anyway, matching Python's own
    // `.replace('\n', ' ')` step).
    let extract = page.get("extract").and_then(|v| v.as_str()).map(|html| {
        html2text::from_read(html.as_bytes(), 100_000).unwrap_or_else(|_| html.to_string())
    });

    Ok(Some(QueryData {
        extract,
        url: page
            .get("fullurl")
            .and_then(|v| v.as_str())
            .map(String::from),
        canonical_title: page.get("title").and_then(|v| v.as_str()).map(String::from),
    }))
}

/// The dominant fix lib/wikipedia_v2.py's docstring describes: one
/// targeted labels request for only the ~10-15 entities this module
/// needs (the 5 wanted properties + their Q-value targets), instead of
/// wptools' `get_wikidata()` -> `get_labels()` cascade that resolves
/// *every* property/value referenced anywhere on the entity (308
/// entities / 7 sequential requests / ~2.8s for IBM, measured there).
async fn fetch_wikidata(
    client: &reqwest::Client,
    title: &str,
) -> anyhow::Result<HashMap<String, serde_json::Value>> {
    let data = get_with_backoff(
        client,
        WIKIDATA_API,
        vec![
            ("action", "wbgetentities".into()),
            ("format", "json".into()),
            ("formatversion", "2".into()),
            ("props", "claims".into()),
            ("sites", "enwiki".into()),
            ("titles", title.into()),
        ],
    )
    .await?;

    let Some(entities) = data.get("entities").and_then(|e| e.as_object()) else {
        return Ok(HashMap::new());
    };
    let Some((_, entity)) = entities.iter().next() else {
        return Ok(HashMap::new());
    };
    if entity.get("missing").is_some() {
        return Ok(HashMap::new());
    }
    let raw_claims = entity
        .get("claims")
        .and_then(|c| c.as_object())
        .cloned()
        .unwrap_or_default();

    // Reduce each claim to its plain value(s) - mirrors
    // lib/wikipedia_v2.py's `_reduce_claims`.
    let qid_re = Regex::new(r"^Q\d+$").unwrap();
    let mut claims: HashMap<String, Vec<String>> = HashMap::new();
    for prop in WANTED_WIKIDATA_PROPS {
        let Some(entries) = raw_claims.get(*prop).and_then(|e| e.as_array()) else {
            continue;
        };
        let mut vals = vec![];
        for ent in entries {
            let snak = ent.get("mainsnak").cloned().unwrap_or_default();
            let datavalue = snak.get("datavalue").and_then(|d| d.get("value"));
            if let Some(v) = datavalue {
                if let Some(id) = v.get("id").and_then(|x| x.as_str()) {
                    vals.push(id.to_string());
                } else if let Some(s) = v.as_str() {
                    vals.push(s.to_string());
                }
            }
        }
        if !vals.is_empty() {
            claims.insert(prop.to_string(), vals);
        }
    }

    // Collect just the entity ids we actually need labels for.
    let mut needed: Vec<String> = vec![];
    for (prop, vals) in &claims {
        needed.push(prop.clone());
        for v in vals {
            if qid_re.is_match(v) {
                needed.push(v.clone());
            }
        }
    }
    needed.sort();
    needed.dedup();

    let mut labels: HashMap<String, String> = HashMap::new();
    if !needed.is_empty() {
        let ldata = get_with_backoff(
            client,
            WIKIDATA_API,
            vec![
                ("action", "wbgetentities".into()),
                ("format", "json".into()),
                ("formatversion", "2".into()),
                ("languages", "en".into()),
                ("props", "labels".into()),
                ("ids", needed.join("|")),
            ],
        )
        .await?;
        if let Some(ents) = ldata.get("entities").and_then(|e| e.as_object()) {
            for (eid, ent) in ents {
                if let Some(lbl) = ent
                    .get("labels")
                    .and_then(|l| l.get("en"))
                    .and_then(|en| en.get("value"))
                    .and_then(|v| v.as_str())
                {
                    labels.insert(eid.clone(), lbl.to_string());
                }
            }
        }
    }

    // Build the labeled {"industry (P452)": [...]} shape - mirrors
    // lib/wikipedia_v2.py's `_build_wikidata_dict`. wptools' own
    // `_update_wikidata` collapses a single-value claim to a *bare
    // string*, not a 1-element list (`if len(vals) == 1: claim = ilabel
    // else: claim.append(ilabel)`) - `get_firmographics` then passes
    // `country`/`cik` straight through without re-wrapping them, so
    // V3's actual JSON output has `"country": "United States"`, not
    // `"country": ["United States"]`. Represented here as
    // `serde_json::Value::String` vs `Value::Array` so
    // `firmographics::build_firmographics` can reproduce that shape
    // exactly instead of always forcing a list.
    let mut out = HashMap::new();
    for (prop, vals) in &claims {
        let plabel = labels
            .get(prop)
            .map(|l| format!("{l} ({prop})"))
            .unwrap_or_else(|| prop.clone());
        let labeled_vals: Vec<String> = vals
            .iter()
            .map(|v| {
                if qid_re.is_match(v) {
                    labels
                        .get(v)
                        .map(|l| format!("{l} ({v})"))
                        .unwrap_or_else(|| v.clone())
                } else {
                    v.clone()
                }
            })
            .collect();
        let value = if labeled_vals.len() == 1 {
            serde_json::Value::String(labeled_vals.into_iter().next().unwrap())
        } else {
            serde_json::Value::Array(
                labeled_vals
                    .into_iter()
                    .map(serde_json::Value::String)
                    .collect(),
            )
        };
        out.insert(plabel, value);
    }
    Ok(out)
}

pub(crate) struct LookupOutcome {
    pub(crate) firmographics: Option<serde_json::Value>,
    // Not read by `lib.rs` yet - V3's response shape has no field for
    // "which title actually resolved" or "was a suffix needed," and
    // matching V3's envelope exactly (docs/plans/v4-server-prototype.md
    // sec10) means not inventing one speculatively. Kept on the struct
    // (not deleted) since a future V4-only diagnostic field is a
    // reasonable ask, not because these are unused by accident.
    #[allow(dead_code)]
    pub(crate) resolved_title: Option<String>,
    #[allow(dead_code)]
    pub(crate) resolved_via_suffix: bool,
    pub(crate) message: String,
}

/// Tries the raw name first (the common case - already an exact title
/// or a genuine Wikipedia redirect), then V3's three suffix candidates
/// in order. **Requires both a page AND an infobox to accept a
/// candidate** - a page existing (`fetch_query` succeeding) is NOT
/// enough on its own. Found live: "Alphabet" and "Meta" both resolve to
/// real, existing pages that aren't companies at all (the writing-system
/// concept article; the "meta" prefix/concept article) - 98 and 6
/// templates respectively on those two pages, zero of either containing
/// "box" in the title. Accepting a page-without-an-infobox as a hit
/// previously produced a real, structural problem: a 200 response with
/// every field "Unknown" except `description` (which reads as on-topic
/// prose about the *wrong* thing) and `type: "Private Company
/// (Assumed)"` - indistinguishable from a real, sparse company lookup
/// unless a caller reads the description text itself. Requiring an
/// infobox to accept a candidate rejects both "Alphabet" and "Meta" as
/// non-matches, which correctly routes them into the suffix-retry path
/// and, since " Inc." exists with a real infobox for both, correctly
/// resolves them (live-verified: bare "Alphabet" now returns fully
/// correct data - real CIK, ISIN, tickers - identical to querying
/// "Alphabet Inc." directly).
async fn resolve_candidate(
    client: &reqwest::Client,
    wikipedia_api: &str,
    raw_name: &str,
) -> anyhow::Result<Option<(String, QueryData, HashMap<String, String>, bool)>> {
    let mut candidates = vec![raw_name.to_string()];
    candidates.extend(SUFFIX_HINTS.iter().map(|s| format!("{raw_name}{s}")));

    for (i, candidate) in candidates.iter().enumerate() {
        let (query, infobox) = tokio::join!(
            fetch_query(client, wikipedia_api, candidate),
            fetch_infobox(client, wikipedia_api, candidate),
        );
        if let (Some(q), Some(ibox)) = (query?, infobox?) {
            return Ok(Some((candidate.clone(), q, ibox, i > 0)));
        }
    }
    Ok(None)
}

/// This is the "go one step further" version of V3's hint: V3 only ever
/// tells the caller what to try next in a `message` string (and even
/// that gets swallowed - see `SUFFIX_HINTS`'s doc comment); this
/// actually makes the calls, so a hit comes back as usable data, not a
/// suggestion the caller has to act on themselves.
pub(crate) async fn lookup_firmographics(
    client: &reqwest::Client,
    raw_name: &str,
) -> anyhow::Result<LookupOutcome> {
    // Fire the Wikidata fetch for `raw_name` concurrently with
    // `resolve_candidate`'s own query+infobox probes, optimistically -
    // found via a real perf-test regression (+54% median latency vs the
    // pre-suffix-hint version): running `resolve_candidate` to
    // completion first and only then fetching Wikidata turned what used
    // to be a 3-way-concurrent fetch (infobox + query + wikidata all at
    // once) into a sequential 2-step pipeline, on the *common* path
    // where no suffix is even needed. In the common case (raw name is
    // already the right title, no suffix retry - true for all 10
    // companies in `perf_tests/companies.py`) this optimistic fetch is
    // exactly the data needed and gets reused below, at zero extra
    // latency cost since it runs alongside `resolve_candidate` rather
    // than after it. Only wasted (one extra, harmless request) on the
    // rarer path where a suffix candidate ends up being the real match.
    let (resolved, optimistic_wikidata) = tokio::join!(
        resolve_candidate(client, WIKIPEDIA_API, raw_name),
        fetch_wikidata(client, raw_name),
    );

    let Some((title, query_data, infobox, resolved_via_suffix)) = resolved? else {
        return Ok(LookupOutcome {
            firmographics: None,
            resolved_title: None,
            resolved_via_suffix: false,
            message: hint_message(raw_name),
        });
    };

    // Wikidata for the CANONICAL title, not the candidate string that
    // happened to match (see `QueryData::canonical_title`'s doc comment
    // for why "Meta Inc." vs "Meta Platforms" matters here). Reuse the
    // optimistic fetch when it's already keyed correctly (no suffix
    // needed, and the raw name wasn't itself a redirect to a different
    // canonical title); otherwise fetch again for the real title - the
    // suffix-needed path was already the slower, rarer one before this
    // fix, so a second request there doesn't reintroduce the regression.
    let wikidata_title = query_data.canonical_title.as_deref().unwrap_or(&title);
    let wikidata = if !resolved_via_suffix && wikidata_title == raw_name {
        optimistic_wikidata?
    } else {
        fetch_wikidata(client, wikidata_title).await?
    };

    let firmographics = firmographics::build_firmographics(RawInputs {
        infobox: Some(&infobox),
        wikidata: &wikidata,
        extract: query_data.extract.as_deref(),
        url: query_data.url.as_deref(),
    });

    let message = if resolved_via_suffix {
        format!(
            "Discovered and returning wikipedia data for the company [{raw_name}] \
             via corporate-suffix hint [{title}]."
        )
    } else {
        format!("Discovered and returning wikipedia data for the company [{raw_name}].")
    };

    Ok(LookupOutcome {
        firmographics: Some(firmographics),
        resolved_title: Some(title),
        resolved_via_suffix,
        message,
    })
}

#[cfg(test)]
mod tests {
    //! Promoted from `experiments/wikipedia-spike/src/main.rs`'s
    //! `#[cfg(test)] mod tests` - deliberately exercises the 429/503 +
    //! Retry-After backoff path, the infobox-presence gate, and the
    //! suffix-hint mechanism against mock servers rather than trusting
    //! any of them reads correctly, since the live spike run found real
    //! household-name companies rarely exercise the suffix/backoff paths
    //! at all.
    use super::*;
    use wiremock::matchers::{method, path, query_param};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    const TEST_USER_AGENT: &str = "company-dns-wikipedia-tests/0.1.0 (test)";

    #[tokio::test]
    async fn retries_after_503_with_retry_after_header() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .respond_with(ResponseTemplate::new(503).insert_header("Retry-After", "1"))
            .up_to_n_times(1)
            .expect(1)
            .mount(&server)
            .await;

        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({"ok": true})))
            .expect(1)
            .mount(&server)
            .await;

        let client = reqwest::Client::builder()
            .user_agent(TEST_USER_AGENT)
            .build()
            .unwrap();
        let url = format!("{}/w/api.php", server.uri());

        let start = std::time::Instant::now();
        let body = get_with_backoff(&client, &url, vec![("action", "query".into())])
            .await
            .expect("should succeed after one retry");
        let elapsed = start.elapsed();

        assert_eq!(body, serde_json::json!({"ok": true}));
        assert!(
            elapsed >= Duration::from_millis(900),
            "expected a ~1s sleep for Retry-After: 1, got {elapsed:?}"
        );
    }

    #[tokio::test]
    async fn gives_up_after_max_retries_on_persistent_503() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .respond_with(ResponseTemplate::new(503).insert_header("Retry-After", "0"))
            .mount(&server)
            .await;

        let client = reqwest::Client::builder()
            .user_agent(TEST_USER_AGENT)
            .build()
            .unwrap();
        let url = format!("{}/w/api.php", server.uri());

        let result = get_with_backoff(&client, &url, vec![("action", "query".into())]).await;
        assert!(
            result.is_err(),
            "persistent 503 should exhaust retries and error, not hang or succeed"
        );
    }

    #[tokio::test]
    async fn suffix_hint_resolves_when_bare_name_is_missing() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .and(query_param("action", "query"))
            .and(query_param("titles", "Fizzbuzz Widgets"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "query": {"pages": [{"missing": true}]}
            })))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .and(query_param("action", "parse"))
            .and(query_param("page", "Fizzbuzz Widgets"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "error": {"code": "missingtitle", "info": "The page you specified doesn't exist"}
            })))
            .mount(&server)
            .await;

        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .and(query_param("action", "query"))
            .and(query_param("titles", "Fizzbuzz Widgets Inc."))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "query": {"pages": [{
                    "extract": "<p>Fizzbuzz Widgets Inc. is a fictional company.</p>",
                    "fullurl": "https://en.wikipedia.org/wiki/Fizzbuzz_Widgets_Inc."
                }]}
            })))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .and(query_param("action", "parse"))
            .and(query_param("page", "Fizzbuzz Widgets Inc."))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "parse": {"parsetree": "<root><template><title> Infobox company </title>\
                    <part><name>industry</name><value> Widget manufacturing </value></part>\
                    </template></root>"}
            })))
            .mount(&server)
            .await;

        let client = reqwest::Client::builder()
            .user_agent(TEST_USER_AGENT)
            .build()
            .unwrap();
        let wikipedia_api = format!("{}/w/api.php", server.uri());

        let resolved = resolve_candidate(&client, &wikipedia_api, "Fizzbuzz Widgets")
            .await
            .expect("request should succeed");

        let (title, query_data, infobox, resolved_via_suffix) =
            resolved.expect("should resolve via the Inc. suffix");
        assert_eq!(title, "Fizzbuzz Widgets Inc.");
        assert!(resolved_via_suffix);
        assert_eq!(
            query_data.url.as_deref(),
            Some("https://en.wikipedia.org/wiki/Fizzbuzz_Widgets_Inc.")
        );
        assert_eq!(
            infobox.get("industry").map(String::as_str),
            Some("Widget manufacturing")
        );
    }

    #[tokio::test]
    async fn rejects_a_real_page_that_has_no_infobox() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .and(query_param("action", "query"))
            .and(query_param("titles", "Prose Concept"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "query": {"pages": [{
                    "extract": "<p>A prose concept is not a company.</p>",
                    "fullurl": "https://en.wikipedia.org/wiki/Prose_Concept"
                }]}
            })))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .and(query_param("action", "parse"))
            .and(query_param("page", "Prose Concept"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "parse": {"parsetree": "<root><template><title>Short description</title></template></root>"}
            })))
            .mount(&server)
            .await;

        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .and(query_param("action", "query"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "query": {"pages": [{"missing": true}]}
            })))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .and(query_param("action", "parse"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "error": {"code": "missingtitle", "info": "doesn't exist"}
            })))
            .mount(&server)
            .await;

        let client = reqwest::Client::builder()
            .user_agent(TEST_USER_AGENT)
            .build()
            .unwrap();
        let wikipedia_api = format!("{}/w/api.php", server.uri());

        let resolved = resolve_candidate(&client, &wikipedia_api, "Prose Concept")
            .await
            .expect("requests should succeed");

        assert!(
            resolved.is_none(),
            "a page without an infobox must not be accepted as a match, even though it exists"
        );
    }

    #[tokio::test]
    async fn hint_message_matches_v3_wording_on_total_miss() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/w/api.php"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "query": {"pages": [{"missing": true}]}
            })))
            .mount(&server)
            .await;

        let client = reqwest::Client::builder()
            .user_agent(TEST_USER_AGENT)
            .build()
            .unwrap();
        let wikipedia_api = format!("{}/w/api.php", server.uri());

        let resolved = resolve_candidate(&client, &wikipedia_api, "Totally Fictional Co")
            .await
            .expect("request should succeed");
        assert!(resolved.is_none());

        assert_eq!(
            hint_message("Totally Fictional Co"),
            "Unable to find a company by the name [Totally Fictional Co]. Maybe you should try \
             an alternative structure like [Totally Fictional Co Inc.,Totally Fictional Co Corp., \
             or Totally Fictional Co Corporation]."
        );
    }
}
