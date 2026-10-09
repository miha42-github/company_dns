//! Verbatim-as-practical port of wptools' `utils.py` infobox-parsing
//! functions, the same source `lib/wikipedia_v2.py` lines 135-234 port
//! from (that module's own docstring: "copied verbatim from wptools'
//! source ... so output is guaranteed byte-identical for the logic that
//! matters, not an approximation" - Finding 6 explains why a hand-rolled
//! first attempt diverged subtly and had to be redone this way).
//!
//! `get_infobox`/`_template_to_dict` only ever call the `find=False`
//! path in Python (`_get_infobox` never passes `find=True`), so the
//! deprecated `_template_to_dict_find`/`_text_with_children` branch is
//! intentionally NOT ported here - it's dead code on the path this
//! project actually exercises, not an omission.
//!
//! roxmltree (read-only, non-validating) stands in for lxml.etree here.
//! Its `Node::descendants()` includes the node itself, matching lxml's
//! `Element.iter()`/`.xpath("//tag")` semantics closely enough that the
//! functions below read as a structural translation, not a
//! reimplementation from a different mental model.

use roxmltree::Node;
use serde_json::{json, Value};

fn tag<'a>(n: &Node<'a, 'a>) -> &'a str {
    n.tag_name().name()
}

/// lxml `elem.text`: the text immediately inside the element, before its
/// first child (or None if the element has no leading text/is empty).
fn elem_text(n: &Node) -> Option<String> {
    n.first_child().and_then(|c| {
        if c.is_text() {
            c.text().map(|t| t.trim().to_string())
        } else {
            None
        }
    })
}

/// lxml `elem.tail`: the text immediately after this element's closing
/// tag, up to the next sibling (or parent close).
fn elem_tail(n: &Node) -> Option<String> {
    n.next_sibling().and_then(|s| {
        if s.is_text() {
            s.text().map(|t| t.trim().to_string())
        } else {
            None
        }
    })
}

/// Port of wptools' `_template_to_text`: `tmpl.itertext()` joined by
/// `|`, wrapped in `{{...}}`. `descendants()` (self included) walking
/// only text nodes reproduces `itertext()`'s "every text node inside
/// this subtree, document order" behavior without also picking up the
/// template's own tail (which lxml's `itertext()` doesn't include
/// either - `descendants()` never ascends past `tmpl` itself).
fn template_to_text(tmpl: Node) -> String {
    let parts: Vec<&str> = tmpl
        .descendants()
        .filter(|n| n.is_text())
        .filter_map(|n| n.text())
        .collect();
    format!("{{{{{}}}}}", parts.join("|").trim())
}

/// Port of wptools' `_template_to_dict_iter` - the only value-extraction
/// path `_get_infobox` actually exercises (see module docs). Walks
/// `item`'s subtree in document order the way lxml's `Element.iter()`
/// does: every `<value>` element's leading text is collected until a
/// `<template>` is seen (after which `<value>` text is ignored - a
/// nested template's own rendered text takes over instead), and every
/// element's `.tail` is appended along the way.
fn template_to_dict_iter(item: Node) -> String {
    let mut valarr: Vec<String> = vec![];
    let mut found_template = false;
    for elm in item.descendants().filter(|n| n.is_element()) {
        let t = tag(&elm);
        if t == "value" && !found_template {
            if let Some(text) = elem_text(&elm) {
                if !text.is_empty() {
                    valarr.push(text);
                }
            }
        }
        if t == "template" {
            found_template = true;
            valarr.push(template_to_text(elm).trim().to_string());
        }
        if let Some(tailtext) = elem_tail(&elm) {
            if !tailtext.is_empty() {
                valarr.push(tailtext);
            }
        }
    }
    valarr
        .into_iter()
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

/// Port of wptools' `_template_to_dict` (the `find=False` path only -
/// see module docs). `tree` is a `<template>` node; its direct children
/// are typically one `<title>` and zero-or-more `<part>` elements.
/// Non-`<part>` children (like `<title>` itself, when this function is
/// called on a template whose children include it) fall into the
/// `except AttributeError` branch in Python (no `name`/`value` children
/// to find) - replicated here as the `else` arm below, keyed by tag name
/// (or `"infobox"` specifically for a `<title>` child, matching Python's
/// special case).
fn template_to_dict(tree: Node) -> Value {
    let mut obj = serde_json::Map::new();
    for item in tree.children().filter(|c| c.is_element()) {
        let t = tag(&item);
        if t == "part" {
            let name = item
                .children()
                .find(|c| c.is_element() && tag(c) == "name")
                .and_then(|n| elem_text(&n).or_else(|| n.text().map(|s| s.trim().to_string())));
            let name = name.or_else(|| {
                // lxml's `findtext('name')` returns the concatenated text
                // of the whole `<name>` subtree, not just its leading
                // text - fall back to that for a `<name>` with nested
                // markup (rare, but seen on some infoboxes).
                item.children()
                    .find(|c| c.is_element() && tag(c) == "name")
                    .map(|n| {
                        n.descendants()
                            .filter(|d| d.is_text())
                            .filter_map(|d| d.text())
                            .collect::<String>()
                            .trim()
                            .to_string()
                    })
            });
            let value = template_to_dict_iter(item);
            if let Some(name) = name {
                let name = name.trim();
                if !name.is_empty() && !value.trim().is_empty() {
                    obj.insert(name.to_string(), json!(value.trim()));
                }
            }
        } else if let Some(text) = elem_text(&item) {
            if !text.is_empty() {
                if t == "title" {
                    obj.insert("infobox".to_string(), json!(text));
                } else {
                    obj.insert(t.to_string(), json!(text));
                }
            }
        }
    }
    Value::Object(obj)
}

/// Port of wptools' `_template_to_dict_alt` - the fallback structure
/// used when `template_to_dict` finds nothing (Python: `if box: return
/// box` first; only reached otherwise). Lower-fidelity by design - this
/// is wptools' own "debug dump" fallback, not the primary data path.
fn template_to_dict_alt(tree: Node, title: &str) -> Value {
    let mut boxes: Vec<Value> = vec![];
    let mut part: Vec<Value> = vec![];
    for item in tree.descendants().filter(|n| n.is_element()) {
        let t = tag(&item);
        if t == "part" {
            if !part.is_empty() {
                boxes.push(json!(part));
                part = vec![];
            }
        }
        if t == "name" || t == "value" {
            for attr in item.attributes() {
                part.push(json!({ attr.name(): attr.value() }));
            }
            if let Some(text) = elem_text(&item) {
                if !text.is_empty() {
                    part.push(json!(text));
                }
            }
            if let Some(tailtext) = elem_tail(&item) {
                if !tailtext.is_empty() {
                    part.push(json!(tailtext));
                }
            }
        }
    }
    if !part.is_empty() {
        boxes.push(json!(part));
    }
    json!({ title.trim(): boxes })
}

/// Port of wptools' `get_infobox` (`_get_infobox` in
/// `lib/wikipedia_v2.py`). `//template` in lxml's xpath means every
/// `<template>` anywhere in the tree, matching `descendants()` here
/// too (not just direct children of the document root).
///
/// One deliberate divergence from the Python: `item.find('title').text`
/// crashes with `AttributeError` if a template has no `<title>` child at
/// all - real wptools/MediaWiki parsetree output always has one, so this
/// was never actually hit in practice, but this port skips such a
/// template instead of panicking, which is strictly safer without
/// changing behavior on any real input.
pub fn get_infobox(parsetree_xml: &str, boxterm: &str) -> Option<Value> {
    let doc = roxmltree::Document::parse(parsetree_xml).ok()?;
    let mut boxes: Vec<Value> = vec![];
    for item in doc
        .descendants()
        .filter(|n| n.is_element() && tag(n) == "template")
    {
        let Some(title_node) = item
            .children()
            .find(|c| c.is_element() && tag(c) == "title")
        else {
            continue;
        };
        let Some(title) = elem_text(&title_node) else {
            continue;
        };
        if !title.contains(boxterm) {
            continue;
        }
        let box_val = template_to_dict(item);
        if box_val.as_object().is_some_and(|o| !o.is_empty()) {
            return Some(box_val);
        }
        boxes.push(template_to_dict_alt(item, &title));
    }
    if !boxes.is_empty() {
        return Some(json!({ "boxes": boxes, "count": boxes.len() }));
    }
    None
}

/// Convenience: most infobox consumers (this spike included) want a
/// flat `{name: value}` map, not the raw `{"boxes": [...]}` fallback
/// shape - returns `None` if `get_infobox` fell back to that shape
/// (i.e. the primary, high-fidelity parse found nothing usable).
pub fn get_infobox_map(parsetree_xml: &str) -> Option<std::collections::HashMap<String, String>> {
    let val = get_infobox(parsetree_xml, "box")?;
    let obj = val.as_object()?;
    if obj.contains_key("boxes") {
        return None;
    }
    Some(
        obj.iter()
            .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
            .collect(),
    )
}
