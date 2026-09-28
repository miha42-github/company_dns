# New company_dns UX: reference use cases for Mediumroast's free data products

Status: **Draft — skeleton, to refine together.** This doc exists to
collect what's already known (the use cases, the data-availability
asymmetries, what's already been prototyped and validated) and lay out
the real open questions, not to hand down a finished design. Most
sections below are starting points.
Owner: michael.hay@mediumroast.io
Scope: the user experience for the new `company_dns` — decided (see
[`go-duckdb-rewrite.md`](go-duckdb-rewrite.md) §6.5) to be Rust +
DataFusion, and reframed (same doc, §1) as **an example OSS project
demonstrating how to use Mediumroast's free IC-classification and
enriched-company data samples**, not a bulk-processing service. This
doc is specifically about the UX/UI layer across all the use cases
below — not the backend architecture (that's `go-duckdb-rewrite.md`)
and not any single use case's internal design in depth (those get their
own docs as needed, e.g. company-classification once §10.2 of
[`ic-similarity-search-poc.md`](ic-similarity-search-poc.md) graduates
into one).

---

## 1. Why this exists, restated plainly

Mediumroast is giving away, as free "taste" samples:

- Several IC classification systems (legacy Japanese SIC, US SIC, an
  older NACE vintage).
- A sample of enriched Wikipedia/EDGAR company data, including versions
  with precomputed embeddings.

Most people downloading these packages won't know what to do with them.
`company_dns` is the example project that shows them — a reference
implementation of real, useful things you can build on top of this
data, not a production system with uptime/scale requirements. That
framing should shape every UX decision below: **clarity and
"here's-how-this-works" legibility matter more than polish or
throughput.**

## 2. The use cases (from go-duckdb-rewrite.md §1, restated here as the UX's job)

1. **Search for SIC/industry codes across multiple IC systems** —
   parity with what the current `html/` Industry Classification
   Explorer already does (search a term, get matches from US SIC, UK
   SIC, EU NACE, ISIC, Japan SIC simultaneously).
2. **Match a company description to one or more IC systems.**
   Single-company-at-a-time (not bulk — see `go-duckdb-rewrite.md` §1's
   correction of an earlier mischaracterization of this as a batch
   capability). A company can legitimately resolve to more than one
   code. Design thinking so far: `ic-similarity-search-poc.md` §10.1
   (chunking long descriptions) and §10.2 (why this is its own
   capability, confidence/triage, multi-code output).
3. **Find companies based on a search** — free-text search over the
   enriched company data samples.
4. **Find companies similar to a given company** — company-to-company
   similarity, using the same enriched/embedded company data.
5. **Issue a SQL query directly against the included cached data** —
   DataFusion's own SQL interface, already proven end-to-end in
   `experiments/ic-similarity-service`.

## 3. A real asymmetry the UX needs to surface honestly

Not everything works the same way everywhere, and pretending otherwise
would undercut the "reference example" purpose (a demo that silently
does something different than it appears to do is a bad demo):

- **Live spillover vs. cached-only.** EDGAR and Wikipedia lookups can
  fall back to the live service on a cache miss (`go-duckdb-rewrite.md`
  §5); the IC/classification data is a static, self-contained sample
  with no live-service equivalent — a miss there is just a miss, there's
  nothing to spill over to.
- **SQL access has the same split**: item 5 above works against
  whatever's actually cached/local. A query that needs live EDGAR/
  Wikipedia data mid-query doesn't have anywhere to spill over to
  either — SQL is a window onto the local DataFusion tables, not a
  general query interface over the live web.
- Open question, not resolved here: how does the UI communicate this
  distinction without turning into a wall of caveats? (A per-feature
  badge? Framing it in the copy right where each feature lives? Only
  surfacing it when a miss actually happens, the way `ic-similarity-
  service`'s truncation warning only appears when truncation is
  actually about to happen, not as a permanent disclaimer?)

## 4. What's already built and validated — worth reusing, not reinventing

`experiments/ic-similarity-service` (built for use case 2's IC-only
slice, and the interactive-search half of the general similarity
mechanism) already has real, tested UX patterns worth carrying forward
rather than redesigning from scratch:

- **Simple/Detailed input tabs** — a single-line box for short queries,
  a textarea for longer text (company descriptions), switchable. Came
  from direct feedback in this session, already validated.
- **Live, input-layer feedback instead of post-submit surprises** — the
  token-count/truncation check fires as the user types, before they
  submit, per direct feedback that a post-search warning is "too late
  in the process." This principle (tell the user what's about to
  happen, not what already happened) is worth applying more broadly
  than just truncation.
- **Calibrated, plain-language result labels instead of raw statistics**
  — `ic-similarity-search-poc.md` §5's whole arc (percentile bands →
  literature search → plain-language "Possible Match"/"Likely Match"
  wording) is directly reusable for any use case that shows a ranked or
  scored result (company search, company similarity, IC matching all
  need this same treatment).
- **Minimal dark theme borrowed from `html/styles.css`'s `:root` tokens**
  — visually consistent with the existing `company_dns` web app without
  dragging in its full Alpine.js SPA machinery, which was overkill for
  a focused tool.
- **Chunk-level match provenance** (proposed, not yet built —
  `ic-similarity-search-poc.md` §10.1's "show which chunk drove a
  match") — valuable for a *reference/example* UX specifically, since
  showing *why* a match happened is teaching value, not just a nice-to-
  have.

**Open question, central to this doc**: does `ic-similarity-service`
graduate into (part of) the real UX, or does the new UX get built fresh,
informed by what was learned there but not literally extending that
codebase? It was built and committed as a disposable `experiments/`
spike (see its own README), not as production-track code — worth an
explicit decision rather than assuming either way.

## 5. Open questions to work through together

- **One app or several?** Is this a single UI with the five use cases
  as tabs/sections (closer to the current `html/` explorer's model —
  one SPA, multiple explorers), or several small, focused tools (closer
  to how `experiments/ic-similarity-service` is scoped — one thing,
  done clearly)? The "reference example" framing could argue either
  way: one app is easier to discover everything from; several small
  tools are each easier to read as a standalone example of one
  technique.
- **Information architecture across the five use cases.** Do IC search
  (1) and company-to-IC matching (2) live together (they're both "how
  do I classify something") separately from company search (3) and
  company similarity (4) (both "how do I find a company")? Does SQL
  access (5) get its own dedicated space (closer to a query console) or
  live as an "advanced" option attached to the others?
- **How much of `ic-similarity-service`'s specific UI (tabs, calibrated
  labels, live checks) transfers as-is vs. needs rethinking** once
  there are five use cases instead of one, some of which have
  different result shapes entirely (a SQL query's output isn't a
  ranked-list-with-similarity-scores the way search results are).
- **What does "example/reference" mean concretely in the UI itself?**
  Inline explanations of what's happening and why (closer to a
  documentation site with live examples) vs. a clean tool that happens
  to be simple enough to read as an example on its own? These pull the
  design in different directions.
- **Company search (3) and company similarity (4) need the enriched
  company data samples** — not yet available to build/test against
  (same constraint noted in `go-duckdb-rewrite.md` §7.7/§7.8 for the
  embedding-model decisions). Worth sequencing the UX work around IC
  search (1) and company-to-IC matching (2) first, where real data
  already exists, and treating 3/4 as designed-but-not-buildable until
  company data samples land.

## 6. Explicitly out of scope

- Bulk/batch operations of any kind (per the reframing — this is
  single-interaction, reference-example usage, not a data pipeline).
- Anything requiring authentication, multi-user state, or persistence
  beyond the cached data itself — matches the current `company_dns`'s
  posture (no accounts, no saved state).
- Production hardening (rate limiting, monitoring, etc.) — out of scope
  for a reference/example project in the way it was very much in scope
  for the *current* Python service (V3.2.0's security hardening work).
  Worth a explicit sentence to that effect somewhere visible in the
  eventual real docs, so nobody mistakes this for a production-ready
  template.

## 7. Next steps

1. React to this skeleton — cut, add, reorder, or flag anything wrong
   before it grows further.
2. Settle §5's "one app or several" and information-architecture
   questions — these shape everything else.
3. Decide §4's "does `ic-similarity-service` graduate or get
   superseded" question.
4. Once IC search (1) and company-to-IC matching (2) have a settled
   shape, start on their concrete UI design; treat company search (3)
   and similarity (4) as blocked on company data availability.
