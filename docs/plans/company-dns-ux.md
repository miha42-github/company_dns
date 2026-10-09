# New company_dns UX: reference use cases for Mediumroast's free data products

Status: **Decided on information architecture and framework (2026-09-
30); visual/page-level design still to build.** §5 records the first
round of real decisions (one app, IA split, SQL kept off this app's
GUI, company search/similarity deferred to V4.1.0). §8-§10 are new:
the UI-framework decision, the visual-direction decision (drawing from
mediumroast.io, a real shift from the current dark theme), and stub
sections per page to design into next. Most of §10 is still empty on
purpose — filling it in is the next work, not something to guess at
here.
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

**Decided (2026-09-30, §5): `ic-similarity-service` is a starting
point to pull in and iterate from, not a finished design to adopt
wholesale, and not left behind either.** It stays a disposable
`experiments/` spike as a codebase (no promotion of that directory
itself into production-track code), but its UI patterns above are
carried forward directly into the real UX design work in §9/§10,
alongside a look at how `html/`'s current implementation does the same
things.

## 5. Decided (2026-09-30): one app, two experiences, SQL kept off this GUI

- **One app, not small tools.** A single SPA with the five use cases
  organized as sections/experiences within it — closer to the current
  `html/` explorer's model than to `ic-similarity-service`'s
  one-thing-done-clearly scoping. Reasoning from the user directly:
  discoverability of the full set of reference use cases from one
  place outweighs each one reading as a standalone example.
- **Information architecture: two experiences, not five flat items.**
  1. **"Industrial Classification Search & Exploration"** — covers use
     case 1 (search SIC/industry codes across systems) *and* use case 2
     (match a company description to one or more IC systems) as one
     coherent experience, since both are "how do I classify something."
     Covers simple search and semantic search together.
  2. **"Company Matters"** — covers use case 3 (company search) and use
     case 4 (company-to-company similarity) as their own experience,
     since both are "how do I find a company." **Deferred to V4.1.0**
     (§3a below) — the enriched company data samples this needs aren't
     available yet, so this experience is designed-but-not-buildable
     for the initial release. Keep it as a real, named section of the
     IA now so the eventual work has a home, not an afterthought bolted
     on later.
  - **Parking lot, not decided**: whether simple SQL-style search and
    semantic search should be combined into one input inside the IC
    experience. Needs more research before deciding — noted here so it
    isn't lost, not because it's blocking anything now.
- **SQL access (use case 5) does NOT get a GUI surface in this app.**
  It warrants a real new backend endpoint (accepts a SQL string, runs
  it against the local DataFusion tables), but that endpoint is not
  exposed in `company_dns`'s own local GUI. That experience — a query
  console — is reserved for the Mediumroast website
  (mediumroast.io), not duplicated here. This app's job is the two
  experiences above; SQL access is a separate product surface entirely.
- **`ic-similarity-service` is a starting point to iterate from, not a
  finished design to adopt wholesale.** Direct instruction: pull the
  existing prototype in as a baseline, look at how the current
  (Python/V3) `html/` implementation does the same things, and iterate
  from there — explicitly "still not satisfied with it" as it stands
  today. See §9/§10 for where that iteration starts (visual direction,
  page-by-page redesign).
- **"Reference/example" framing doesn't mean cramming every
  explanation into the app.** There are several surfaces available for
  that job: this app itself (it already has a landing-page sense of
  this, which needs reshaping — §10.1), plus the GitHub repo itself and
  a reshaped GitHub Pages site. Split the explanatory burden across
  those surfaces rather than making the app carry all of it.

## 6. Explicitly out of scope

- SQL access (use case 5) as a GUI surface in this app — real endpoint,
  no local UI for it; reserved for the Mediumroast website (§5).
- Company search (use case 3) and company similarity (use case 4) for
  this release — designed as part of the "Company Matters" experience
  (§5) but **deferred to V4.1.0**, gated on the enriched company data
  samples landing (same constraint as `go-duckdb-rewrite.md` §7.7/§7.8).
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

1. Fill in §10's page-by-page redesign stubs, starting with the
   landing page and the IC Search & Exploration experience (real data
   exists for both now).
2. Pull `ic-similarity-service`'s UI and `html/`'s current Industry
   Classification Explorer in as the two reference points for that
   redesign (§5) — not a rewrite from a blank page.
3. Once the IC experience has a settled concrete design, treat
   "Company Matters" (§5) as designed-but-not-buildable until company
   data samples land (V4.1.0) — keep its stub in §10 moving in the
   meantime so the shape is ready when data arrives.
4. Reshape the app's landing page and the GitHub Pages site per §5's
   surface-splitting decision, once the in-app IC experience redesign
   is far enough along to know what it no longer needs to explain
   inline.

## 8. Open: UI framework

Not decided yet. The real choice is narrower than "any JS framework" —
both existing reference points already picked the same thing for the
same reasons:

- **V3's `html/` app**: Alpine.js 3.x + vanilla JS, no build step, a
  single static asset bundle served directly.
- **`ic-similarity-service`**: plain HTML/vanilla JS, no framework at
  all, same no-build-step posture.

**Recommendation, not yet decided**: keep that pattern — Alpine.js (or
even drop to vanilla JS, given how thin `ic-similarity-service`'s needs
turned out to be) rather than adopting a Rust-native WASM framework
(Leptos, Yew, Dioxus). Reasoning:

- The "reference example" framing (§1) favors a reader being able to
  open one `index.html` and a couple of small JS files and understand
  the whole thing — a WASM toolchain adds a build step, a much larger
  learning curve, and bytecode a reader can't just read, all of which
  cut against that goal.
- The backend is Rust; the frontend doesn't need to be for this
  project's purpose. Nothing about `company_dns`'s reference-example
  goal is demonstrating a Rust frontend — it's demonstrating the data
  APIs.
- Both this project's own prior art (`html/`) and the most recent
  prototype built specifically for this problem (`ic-similarity-
  service`) independently converged on the same lightweight choice
  without being told to.
- This is served as static files from the Axum binary either way (no
  separate frontend server), so there's no backend-integration reason
  to pick a Rust-specific option.

Still open: Alpine.js (richer reactive state, already proven at `html/`
app scale) vs. plain vanilla JS (what `ic-similarity-service` actually
needed, given its narrower scope). Worth revisiting once §10's IC
experience has a concrete design — the answer may differ once "one
app, two experiences" adds enough shared state (tab switching between
experiences, shared search-input components) to make Alpine.js's
reactivity worth its weight again.

## 9. Visual direction: draw from mediumroast.io, not the current dark theme

**Decided directly**: "I don't really like the current UI so much and
while we want to keep the coloring the same we should try to draw from
the style found in [mediumroast.io](https://www.mediumroast.io)." Two
things follow from that, and they pull in different directions on
purpose — reconcile them, don't pick one:

- **Keep the coloring** — the existing token palette (`html/
  styles.css`'s `:root`, also what `ic-similarity-service` borrowed
  from): `--color-orange` (#ca703f-family) for primary accents/CTAs,
  `--color-link-primary` (#1696c8, blue) for links/secondary accents,
  the neutral text-primary/text-secondary pairing. This is brand
  continuity across the whole company_dns/Mediumroast surface — not up
  for revisiting here.
- **Don't keep the current dark theme or layout language.** Live-
  checked mediumroast.io directly (2026-09-30) rather than going from
  memory — it is a **light** theme, and the concrete patterns worth
  carrying over are specific, not vague "make it nicer":
  - Near-black top nav bar (`#0F0D0E`-family — actually the same value
    as `html/styles.css`'s current dark-theme *background* token,
    repurposed here as a nav-bar-only dark accent against an otherwise
    light page, not the whole page background).
  - Light, mostly-white body background — a real reversal from
    `html/`'s all-dark theme, not a tweak to it.
  - Large, bold, black sans-serif headlines (system `Helvetica
    Neue`/`Helvetica`/`Arial` stack) as the dominant typographic voice,
    not accent-colored headings.
  - Small, uppercase, letter-spaced "eyebrow" labels in the blue accent
    color above section headings (e.g. "PRODUCT FAMILIES") — a pattern
    `company_dns` doesn't currently have anywhere and is worth adopting
    for section/experience labels (e.g. above "Industry Classification
    Search & Exploration").
  - White content cards with soft shadows and generous rounded corners
    on a light gray/white page background, replacing `html/`'s flat
    dark result-card treatment.
  - Orange used specifically for primary CTAs and card-heading accents
    (rendered as filled pill buttons, fully rounded — `border-radius:
    999px`), not as a general-purpose text color the way `html/`
    currently uses it more broadly.
  - "COMING SOON" as a small rounded pill badge — directly reusable for
    the "Company Matters" experience (§5/§6) once it's visible in the
    IA but not yet buildable, exactly the situation mediumroast.io uses
    this pattern for on its own "Company Data" card.
  - Photographic/textured hero imagery (coffee beans, on-brand) behind
    the top headline — likely not something `company_dns` needs to
    replicate (a data-exploration tool isn't a marketing homepage), but
    worth an explicit "considered, not adopting" note rather than
    silently ignoring it.

Net effect (as originally decided): this is a **light-theme redesign
that keeps the existing brand colors**, not a re-skin of the current
dark theme. That's a bigger visual change than "restyle" might imply —
worth surfacing explicitly so it isn't assumed to be a light touch-up
when design work actually starts.

**Revised (2026-09-30), after seeing the step-1 Home page built
light**: "Can we do a dark version of this instead of the exact colors
for mediumroast.io? I'm interested in there being a clear visual
separation between the two." This splits the decision above into two
separable parts and overrides one of them:

- **Keep**: the mediumroast-inspired *layout/typographic patterns* —
  eyebrow label, bold large headline as the dominant voice, a card
  with soft shadow and heavy rounding for the search block, pill-
  shaped CTAs and toggles, a "coming soon" pill badge. These transfer
  regardless of light or dark.
- **Reverse**: the *light palette itself*. Not adopted — a dark
  palette instead, explicitly so `company_dns` doesn't read as a
  mediumroast.io reskin. Built (Home tab only, `static/styles.css`
  `.home-*` rules) by reusing this app's own existing three-tier dark
  background scale (`--color-bg-primary` nav → `--color-bg-secondary`
  page → `--color-bg-tertiary` card → `--color-bg-primary` input
  field again) so nav/page/card read as distinct elevated layers — the
  "clear visual separation" comes from that layering, not from a
  light/dark contrast against the nav. Existing brand color tokens
  (orange/blue) unchanged and still carry all the same jobs (CTAs,
  eyebrow, links).

So: pattern-matching mediumroast.io, not palette-matching it. The
"draw from mediumroast.io" instruction was about *shape*, and the
exact-color reading was the wrong takeaway from it — worth remembering
for the remaining unbuilt pages in §10.

## 10. Page-by-page redesign stubs

Placeholders — one per page/experience in the decided IA (§5). Fill
each in as design work actually starts on it; do not pre-design here.

### 10.1 Landing / home page

Current state: `html/index.html`'s Help tab already carries some of
this load (API docs, endpoint reference, feature walkthroughs — see
`html/README.md`). Per §5, reshape rather than discard: decide what
moves out to the GitHub repo/GitHub Pages vs. what the in-app landing
experience still needs to carry (first-run orientation, links into the
two experiences below, the "reference example" framing from §1 stated
plainly). Not started.

### 10.2 Industry Classification Search & Exploration

Covers use cases 1 (multi-system IC search) and 2 (company-description
→ IC match, with semantic search and chunking). Reference points to
pull from per §5: `ic-similarity-service`'s simple/detailed input tabs,
live truncation feedback, and calibrated result labels; `html/`'s
current Industry Classification Explorer for the multi-system
search/filter/pagination pattern. Not started.

### 10.3 Company Matters

Covers use cases 3 (company search) and 4 (company-to-company
similarity). **Deferred to V4.1.0** (§5/§6) — data not yet available
to build or test against. Keep this stub present in the IA now (with a
"COMING SOON" treatment per §9) so the eventual design has a known slot
rather than being bolted on later. Not started, not blocked on this
doc — blocked on company data sample availability.

**Update (2026-10-04): the existing company lookups now share the IC
explorer's look and feel.** EDGAR and Wikipedia were two differently-styled
pages (a big heading, an intro paragraph and a centered pre-search card on
EDGAR; a narrow centered column on Wikipedia). Both now sit in the same shell as
the Industry Classification Explorer: a "Company Explorer" breadcrumb, an
`EDGAR | Wikipedia` mode tab row, a bare pinned search bar, a sidebar and a
results header, no page heading or intro. Switching tabs carries the query across
and runs it in the other mode unless it already shows it, as the IC tabs do.
The shared IC layout rules were extended to the two company pages rather than
duplicated (`styles.css`, `#GlobalSearch` / `#EdgarExplorer` /
`#WikipediaResults`). The page is titled "Company Explorer" to mirror "Industry
Classification Explorer"; this section's IA name, "Company Matters", is still the
name for the whole experience once company-to-company similarity (V4.1.0) lands.
**Merged tab (same day).** The tab row is now `Merged | EDGAR | Wikipedia`, and
Merged is attached to `/V4.0/global/company/merged/firmographics/{name}`: one
company card with source chips lit for each source that contributed (EDGAR,
Wikipedia), a "matched by CIK" / "matched by name" badge, the key facts (industry,
location, listings, ISIN, CIK, 10-x filings on file, latest 10-K and 10-Q), recent
filing links, SEC quick links, and the Wikipedia description last (it is long and
would otherwise push the facts below the fold). A missing source is explained in
the card from the endpoint's own `note` ("3 EDGAR companies match this name...",
"Wikipedia reports CIK N, but the loaded EDGAR catalog has no filings for it").
It resolves names EDGAR's own name search cannot ("International Business
Machines" and "IBM" via Wikipedia's CIK). The Home page's Company panel gets a
matching `Merged` pill; the default mode there is unchanged (EDGAR). Not done:
making Merged the default company mode, as Combined is for IC.

### 10.4 SQL access

Not a page in this app — explicitly kept off this GUI entirely (§5/§6),
reserved for mediumroast.io's own query-console experience. No stub
needed here.
