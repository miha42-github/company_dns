# V4 OpenAPI docs (`/docs`, `/redoc`, `/openapi.json`) + V3.0 URL aliases

Status: **Built (2026-09-28) — real, running, live-verified.** All 24
paths (12 `/V4.0/` + 11 `/V3.0/` aliases + `/health`) serve from a real
`utoipa`-generated spec at `/openapi.json`; Swagger UI at `/docs`
(redirects to `/docs/`) and ReDoc at `/redoc` both render live;
`perf_tests/baseline.py`'s `verify_endpoints_exist` now validates
against V4's spec instead of warning-and-skipping (confirmed: the
"could not fetch/parse... expected for the V4 prototype server" warning
no longer appears); a `/V3.0/` alias and its `/V4.0/` counterpart
return byte-identical bodies for EDGAR-by-CIK, Wikipedia, and merged
firmographics (SIC description differs only in row *order* across
repeated calls to the *same* URL too - a pre-existing DataFusion
`ORDER BY`-less query, unrelated to this work, not a regression). Axum
upgraded 0.7 → 0.8 as a prerequisite (§2) - the real migration surface
turned out to be exactly what was predicted (route-path syntax only),
plus one real bug found and fixed during implementation not predicted
by the plan: `routes!(a, b)` bundles handlers that share **one path**
across HTTP methods, not multiple different paths - bundling a
`/V4.0/` handler with its `/V3.0/` alias in one call panicked at
startup ("Overlapping method route... both GET"); fixed by giving every
handler, including every alias, its own `.routes(routes!(handler))`
call (§3.3, updated). A second, smaller fix: `ApiDoc`'s `#[openapi(...)]`
must NOT also list `paths(...)` when routes are registered via
`OpenApiRouter::with_openapi(...).routes(routes!(...))` - doing both
double-registers every path with Axum, same panic. `ApiDoc` now carries
only `info`/`components`; every path comes from exactly one
`routes!(...)` call, nowhere else.
Owner: michael.hay@mediumroast.io
Scope: give `v4/crates/server/` the same three introspection routes
FastAPI gives V3 for free — `/docs` (Swagger UI), `/redoc` (ReDoc), and
`/openapi.json` (the raw spec) — using `utoipa`, the standard Rust
equivalent. Answers the gap flagged in
[`v4-server-prototype.md`](v4-server-prototype.md) §9 ("An
OpenAPI-equivalent discovery endpoint is worth keeping... not built
yet") and closes a real hole in `perf_tests/baseline.py`'s
`verify_endpoints_exist`, which currently has to skip drift-checking
against V4 entirely because there's nothing to check against
(`baseline.py`'s own comment: *"This is expected for the V4 prototype
server, which has no OpenAPI spec yet"*). **Extended (same request)**
to also cover backwards compatibility: serving V3's `/V3.0/` URL paths
alongside `/V4.0/` for the resources V4 actually implements, so an
existing caller pointed at those older paths keeps working when V4
replaces V3 — §8. **Decided (2026-09-28): `/V2.0/` is explicitly out of
scope, `/V3.0/` only** — V2 is the oldest, least-current URL shape
still in V3's own router (predates even the `/na/`-style regional
prefix); carrying it forward into V4 would mean permanently supporting
a second legacy shape indefinitely for no live-usage evidence it needs
it, whereas `/V3.0/` is the shape V3's own current deployment actually
serves today. **Reversed 2026-10-07 by the owner: V3's limited legacy `/V2.0/` set (11 paths: US SIC five, EDGAR four, Wikipedia and merged firmographics) is
served again**, as aliases answered exactly like their `/V3.0/` twins (V3 itself served both URLs with the same handler), documented in `/docs` and on the About page;
see `v4-release-to-staging.md`. **Decided: build the documented alias wrapper functions**
(§8.3's option (b)) — the legacy paths appear in `/docs`/`/openapi.json`
alongside `/V4.0/`, not silently.

---

## 0. Why this doc

Raised directly: *"Do we have an OpenAPI docs site just like the
Python version?"* — no. V3's FastAPI app gets `/docs`/`/redoc`/
`/openapi.json` automatically from its route decorators and Pydantic
models (`company_dns.py:99-106`):

```python
app = FastAPI(
    title="company_dns API",
    description="Company firmographics and SIC code lookup service",
    version="3.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
```

Axum has no equivalent built in — `v4/crates/server/src/main.rs`'s
router is hand-wired `.route(path, get(handler))` calls with no schema
introspection at all. `utoipa` (+ its Axum/Swagger-UI/ReDoc companion
crates) is the standard way to add this to an Axum service, generating
the spec from annotated handlers rather than a separate hand-maintained
document that drifts.

## 1. A finding that changes the scope: V3's own spec is generic, not per-endpoint-typed

Checked `lib/models.py` before assuming this needs deep per-endpoint
schemas. It doesn't — **every V3 response model is the same class**:

```python
class BaseAPIResponse(BaseModel):
    code: int = Field(..., ge=200, le=599)
    message: Optional[str] = None
    module: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    dependencies: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(extra='allow', ...)

SICResponse = BaseAPIResponse
EdgarCIKResponse = BaseAPIResponse
WikipediaResponse = BaseAPIResponse
MergedFirmographicsResponse = BaseAPIResponse
# ... every other response model is the same alias
```

`data: Dict[str, Any]` means V3's actual OpenAPI spec has **no
field-level schema for any endpoint's payload** — every route's
response schema is the same generic envelope with an open `data`
object. **This means real V3 parity here does not require typed Rust
structs per endpoint** (`SicMatch`, `EdgarDetail`, etc.) — one generic
envelope schema, applied to every route, is what V3 itself actually
publishes. Worth stating explicitly since it's the natural thing to
overbuild: matching V3 means matching this genericness, not improving
on it unprompted.

## 2. Crates (checked live against crates.io, 2026-09-28)

**Found during implementation, resolved the same day: `utoipa-axum`/
`utoipa-swagger-ui`/`utoipa-redoc` all require `axum ^0.8.4`** (checked
via crates.io's own dependency API, not assumed), while this workspace
pinned `axum = "0.7"` (`v4/Cargo.toml`). **Decided: upgrade to axum
0.8, not work around it** - v4 is pre-release, and the actual migration
surface for this specific codebase is small, checked concretely rather
than assumed risky:

- **Path syntax**: `:param` → `{param}` in the ~12 existing route
  strings (`v4/crates/server/src/main.rs`) - mechanical.
- **`tower-http` 0.6** (already pinned) depends on `http ^1.0`/
  `http-body ^1.0` directly, not on axum's version - already exactly
  what axum 0.8 needs. No conflict (confirmed via crates.io's
  dependency API, not the changelog alone).
- Every other axum 0.8 breaking change (`async_trait` import,
  `Option<T>` extractor's new required trait, WebSocket `Message`
  type, `Host` extractor's move to `axum-extra`, `tcp_nodelay`
  removal, `get_service` removal) - **none apply**: checked against
  actual usage in `v4/crates/server`, which only touches `Router`,
  `State`, `Path`, `Query`, `get`, `IntoResponse`, `Json`, `CorsLayer`,
  `axum::serve`.

This keeps the original design intact - `utoipa-axum`'s real guarantee
(route registration and spec generation happen in the same call, so
they can't silently drift apart) rather than a hand-maintained
fallback with a real double-bookkeeping risk.

| crate | version | purpose |
|---|---|---|
| `axum` | 0.8 (up from 0.7) | prerequisite for the three crates below |
| [`utoipa`](https://crates.io/crates/utoipa) | 6.0.0 | derive macros (`#[derive(ToSchema)]`, `#[utoipa::path(...)]`), spec generation |
| [`utoipa-axum`](https://crates.io/crates/utoipa-axum) | 0.3.0 | `OpenApiRouter`, a drop-in `axum::Router` replacement that registers a route's path/method into the spec at the same call site it registers the handler |
| [`utoipa-swagger-ui`](https://crates.io/crates/utoipa-swagger-ui) | 10.0.1 | serves the Swagger UI page (V3's `/docs`) from the generated spec |
| [`utoipa-redoc`](https://crates.io/crates/utoipa-redoc) | 7.0.0 | serves a ReDoc page (V3's `/redoc`) from the same spec |

All actively maintained, high download counts, no red flags — same
evaluation rigor `experiments/wikipedia-spike/README.md`'s crate check
used.

## 3. Design

### 3.1 The one shared response schema

```rust
// v4/crates/server/src/envelope.rs
use utoipa::ToSchema;

#[derive(serde::Serialize, ToSchema)]
pub struct ApiEnvelope {
    /// HTTP status code, duplicated in the body (V3's own convention)
    pub code: u16,
    pub message: String,
    pub module: String,
    /// Open object - matches V3's `Dict[str, Any]` / `extra=allow`,
    /// per sec1's finding. NOT a typed per-endpoint payload.
    #[schema(value_type = Object)]
    pub data: serde_json::Value,
    #[schema(value_type = Object)]
    pub dependencies: serde_json::Value,
}
```

The existing `envelope()`/`ok()`/`not_found()`/`server_error()` helper
functions in `v4/crates/server/src/envelope.rs` keep building
`serde_json::Value` exactly as they do today — `ApiEnvelope` exists
only to give `utoipa` something to point `#[utoipa::path(...)]`
annotations at for the response schema; it does not replace the
existing envelope-building code or require touching any handler's
internal logic.

### 3.2 Per-handler annotation

Every existing handler gets a `#[utoipa::path(...)]` attribute directly
above its `fn` — no change to the handler body itself. Example for
`sic_description`:

```rust
#[utoipa::path(
    get,
    path = "/V4.0/na/sic/description/{sic_desc}",
    params(("sic_desc" = String, Path, description = "SIC description search term")),
    responses((status = 200, description = "SIC matches", body = ApiEnvelope)),
    tag = "SIC (V4.0)"
)]
async fn sic_description(...) -> impl IntoResponse { /* unchanged */ }
```

`tag` groups routes in the Swagger UI sidebar - mirror V3's existing
FastAPI `tags=[...]` groupings (`"SIC (V4.0)"`, `"EDGAR (V4.0)"`,
`"Wikipedia (V4.0)"`, `"System"`) so a reader familiar with V3's
`/docs` page finds the same organization.

### 3.3 Router migration: `axum::Router` → `utoipa_axum::router::OpenApiRouter`

`OpenApiRouter` wraps `axum::Router` (same `.layer()`, `.with_state()`,
etc. all still work) but adds `.routes(routes!(handler))`, which
registers the route with Axum **and** records its `#[utoipa::path]`
metadata into the spec being built, in one call. The existing
`.route("/health", get(health))`-style calls become
`.routes(routes!(health))` once `health` has its `#[utoipa::path]`
attribute (and its path string moves from `:param` to `{param}` syntax,
per §2's axum 0.8 note).

**Corrected during implementation: `routes!(a, b)` is ONE path, not
many.** The macro bundles multiple handlers only when they share a
single route and differ by HTTP method (e.g. `routes!(get_todo,
post_todo)` on one `/todos` path) - not multiple different paths.
Passing `sic_description` and `sic_code` (two different URLs) into one
`routes!(...)` call mounts both as `GET` on the *same* route entry and
panics at startup ("Overlapping method route... both handle GET"). Hit
this exactly, fixed by giving every handler - the primary `/V4.0/`
handler and every `/V3.0/` alias alike - its own `.routes(routes!(...))`
call:

```rust
let (router, api) = OpenApiRouter::with_openapi(ApiDoc::openapi())
    .routes(routes!(health))
    .routes(routes!(sic_description))
    .routes(routes!(sic_description_v3))
    .routes(routes!(sic_code))
    .routes(routes!(sic_code_v3))
    // ...one .routes(routes!(handler)) call per handler, no bundling...
    .routes(routes!(sic_similarity))
    .with_state(state)
    .split_for_parts();

let app = router
    .merge(SwaggerUi::new("/docs").url("/openapi.json", api.clone()))
    .merge(Redoc::with_url("/redoc", api))
    .layer(CorsLayer::permissive());
```

`ApiDoc::openapi()` (§3.4) seeds `info`/`components` into the builder;
`with_openapi(...)` does NOT need (and must not receive) a `paths(...)`
list of its own - each `.routes(...)` call is the sole source of a
path's entry in the final spec. `ApiDoc` listing paths too would
double-register them (§0's status line - the second bug hit during
implementation).

### 3.4 The `OpenApi` document's own metadata

```rust
#[derive(utoipa::OpenApi)]
#[openapi(
    info(title = "company_dns API (V4)", version = "4.0.0",
         description = "Company firmographics and SIC code lookup service"),
    components(schemas(ApiEnvelope))
)]
struct ApiDoc;
```

Matches V3's FastAPI `title`/`description` (`company_dns.py:100-102`)
verbatim except `version` (`"4.0.0"`, not `"3.2.0"` - each server
reports its own, the same rule already applied to `/health`'s
`version` field, §5.3 of `v4-server-prototype.md`).

## 4. What this does NOT do (deliberately, per sec1's finding)

- No per-endpoint typed response schemas (`SicMatch`, `EdgarDetail`,
  etc.) - V3 doesn't have them either, and adding them would be
  building something V3-parity doesn't call for. Revisit only if V4's
  response shapes are ever meant to diverge from V3's on purpose (per
  `v4-server-prototype.md` §10's deferred breaking-change question for
  V4-only endpoints), at which point real schemas become worth the
  cost for documenting *that* divergence specifically.
- No request-body schemas - every V4 endpoint today is a bare `GET`
  with path params only, matching V3.
- No auth/rate-limiting on `/docs`/`/redoc`/`/openapi.json` - V3
  doesn't gate them either (`company_dns.py`'s FastAPI init passes no
  auth dependency to `docs_url`/`redoc_url`).

## 5. Downstream benefit: `perf_tests/baseline.py` can stop skipping V4

`verify_endpoints_exist` (`perf_tests/baseline.py`) already tries
`GET {base_url}/openapi.json` and warns-and-skips when it 404s -
exactly what happens against V4 today. Once this plan ships,
`--profile v4` runs get the same drift-check V3 already gets (refusing
to run if a path this suite depends on isn't actually in V4's spec)
instead of silently trusting the `ENDPOINTS` catalog's `v4_path`
entries are still accurate. No code change needed in `baseline.py`
itself - it already has this logic, just nothing to check against yet.

## 6. Implementation steps — all done (2026-09-28)

1. ~~Bump `axum` to `"0.8"`...~~ **Done.** Route strings converted
   `:param` → `{param}`; the predicted-small migration surface held -
   only the path syntax needed touching.
2. ~~Add `utoipa`, `utoipa-axum`, `utoipa-swagger-ui`, `utoipa-redoc`...~~
   **Done**, versions exactly per §2's table.
3. ~~Add `ApiEnvelope`...~~ **Done**, `v4/crates/server/src/envelope.rs`.
4. ~~Add `#[utoipa::path(...)]` to each of the 12 existing handlers...~~
   **Done.**
5. ~~Migrate the router...~~ **Done**, with the two fixes §3.3/§0's
   status line describe (no bundled `routes!(a, b)`, no `paths(...)`
   on `ApiDoc`).
6. ~~Extract `..._impl`, add `..._v3` wrappers...~~ **Done** for all 11
   aliasable resources - `edgar_detail`/`edgar_summary` didn't need a
   separate `_impl` extraction (they already delegated to the shared
   `edgar_grouped_response` helper); the other 9 got a small `_impl`
   function each.
7. Build, then verify — **all done, live**:
   - `curl localhost:4000/openapi.json` - real spec, all 24 paths
     present (12 `/V4.0/` + 11 `/V3.0/` + `/health`), correctly tagged.
   - `curl localhost:4000/docs` → 303 → `/docs/` → 200 (Swagger UI).
   - `curl localhost:4000/redoc` → 200 (ReDoc).
   - `/V3.0/` aliases confirmed byte-identical to their `/V4.0/`
     counterparts for EDGAR-by-CIK, Wikipedia, and merged firmographics;
     SIC description matches in content (row order varies run-to-run
     even for the *same* URL called twice - a pre-existing DataFusion
     query characteristic, not introduced by this work).
   - `perf_tests/baseline.py --profile v4`'s `verify_endpoints_exist`
     confirmed to validate against V4's real spec now (the "no OpenAPI
     spec yet" warning no longer appears); full 52-call `--profile v4`
     run still 52/52 OK, performance unaffected.
   - Re-run `perf_tests/baseline.py --base-url http://localhost:4000
     --profile v4` and confirm `verify_endpoints_exist` now actually
     checks against V4's spec instead of warning-and-skipping (§5).

## 8. Backwards compatibility: documented `/V3.0/` aliases alongside `/V4.0/`

Requested directly: existing callers pointed at V3's `/V3.0/` URLs
should keep working once V4 is what's actually running, and those
alias paths should be real, documented entries in `/docs`/
`/openapi.json` - not a silent, undocumented fallback.

### 8.1 What V3 actually serves at `/V3.0/` (checked against `company_dns.py`)

Every `/V3.0/`/`/V4.0/` route for the same resource is registered on
the exact same handler function in V3 (`_handle_request(HandlerClass,
method_name, ...)`, `company_dns.py:50`) - the URL prefix is the only
thing that differs, never the logic or response shape. That pattern
translates directly: V4 aliasing `/V3.0/` means a thin wrapper function
that calls the same underlying logic as its `/V4.0/` counterpart, not
new logic.

Sorting V3's full `/V3.0/` path list against what V4 actually
implements today (`v4-server-prototype.md` §1's scope):

**Can alias now (V4 has the real implementation):**

| resource | V3.0 | V4.0 (existing) |
|---|---|---|
| SIC description/code/division/industry/major (US only) | `/V3.0/na/sic/{..}` | `/V4.0/na/sic/{..}` |
| EDGAR ciks/detail/summary | `/V3.0/na/companies/edgar/{..}` | `/V4.0/na/companies/edgar/{..}` |
| EDGAR firmographics by CIK | `/V3.0/na/company/edgar/firmographics/{cik}` | `/V4.0/na/company/edgar/firmographics/{cik}` |
| Wikipedia firmographics | `/V3.0/global/company/wikipedia/firmographics/{name}` (+ its explicit `/v2/` alias, same backend) | `/V4.0/global/company/wikipedia/firmographics/{name}` |
| Merged firmographics | `/V3.0/global/company/merged/firmographics/{name}` (+ its explicit `/v2/` alias) | `/V4.0/global/company/merged/firmographics/{name}` |

**Update 2026-10-07: the non-US per-system endpoints (EU NACE, ISIC, Japan; UK stays out) are now built and aliased, in V3's exact response shape, and so are the two explicit `/v2/` Wikipedia and merged URLs (`v4-release-to-staging.md`, New E). The text below is the original analysis, kept as the record.**

**Cannot alias — no real V4 backend exists, aliasing would 404 or (worse) misleadingly claim support:**

- **All non-US SIC systems** — `/uk/sic/*`, `/eu/sic/*`,
  `/international/sic/*` (ISIC), `/japan/sic/*`, and the cross-system
  `/V3.0/global/sic/description/{query}` (searches *all* systems at
  once) all depend on `lib/uk_sic.py`/`lib/eu_sic.py`/
  `lib/international_sic.py`/`lib/japan_sic.py`, none of which have a
  V4 equivalent — explicitly out of scope per `v4-server-prototype.md`
  §1 ("the other four SIC systems... US SIC only, matching what's
  actually been spiked"). Not something this plan can alias without
  first building those systems in V4 — a separate, much larger body of
  work, not a routing decision.
- **The legacy wptools-backed "v1" Wikipedia/merged variants**
  (`/V3.0/global/company/wikipedia/v1/firmographics/{name}`,
  `/V3.0/global/company/merged/v1/firmographics/{name}`) — V4's
  Wikipedia client (`v4/crates/wikipedia/`) is a hand-rolled `reqwest`
  port of V3's **v2** backend specifically
  (`experiments/wikipedia-spike/README.md`'s crate-evaluation section:
  deliberately not wptools), with no wptools-equivalent at all. V4 has
  nothing to serve at a `/v1/` path that would actually mean "the
  legacy wptools engine" - aliasing it to the same v2-equivalent client
  the default/`/v2/` paths already use would silently misrepresent
  which engine answered the request. **Recommendation: don't alias
  these two specific paths.** A caller relying on `/v1/`'s specific
  wptools quirks (real ones exist - `lib/wikipedia_v2.py`'s own
  docstring documents behavioral differences from `lib/wikipedia.py`)
  needs the actual V3 deployment, not a V4 standing in for it.

### 8.2 Implementation shape: documented wrapper functions, one per aliasable resource

**Decided**: build the alias as its own thin handler function carrying
its own `#[utoipa::path]`, not a bare `.route(...)` call piggybacking
on the `/V4.0/` handler's annotation - so the `/V3.0/` path is a real,
separate, documented entry in `/docs`/`/openapi.json`, matching how V3
itself documents both prefixes as distinct routes today
(`company_dns.py`'s own decorators repeat `tags=[...]`/`summary=...`
per version). Each wrapper calls straight into the same shared
implementation the `/V4.0/` handler already uses - no duplicated logic,
just a second thin entry point:

```rust
#[utoipa::path(
    get,
    path = "/V4.0/na/sic/description/{sic_desc}",
    params(("sic_desc" = String, Path, description = "SIC description search term")),
    responses((status = 200, description = "SIC matches", body = ApiEnvelope)),
    tag = "SIC (V4.0)"
)]
async fn sic_description(
    State(state): State<Arc<AppState>>,
    Path(sic_desc): Path<String>,
) -> impl IntoResponse {
    sic_description_impl(&state, &sic_desc).await
}

#[utoipa::path(
    get,
    path = "/V3.0/na/sic/description/{sic_desc}",
    params(("sic_desc" = String, Path, description = "SIC description search term")),
    responses((status = 200, description = "SIC matches", body = ApiEnvelope)),
    tag = "SIC (V3.0, alias)"
)]
async fn sic_description_v3(
    State(state): State<Arc<AppState>>,
    Path(sic_desc): Path<String>,
) -> impl IntoResponse {
    sic_description_impl(&state, &sic_desc).await
}

// The actual logic, unchanged from what `sic_description` does today -
// both thin wrappers above just call this.
async fn sic_description_impl(state: &AppState, sic_desc: &str) -> impl IntoResponse { /* existing body */ }
```

Registered the same way as any other annotated handler - **as two
separate calls**, not bundled (§3.3's corrected finding: `routes!(a,
b)` is for one path across HTTP methods, not two different paths):

```rust
.routes(routes!(sic_description))
.routes(routes!(sic_description_v3))
```

11 resources get this treatment (5×SIC, 3×EDGAR-by-name, 1×EDGAR-by-
CIK, Wikipedia, merged) → **11 new thin wrapper functions plus 11 small
`_impl` extractions** from the existing handlers. `sic_similarity`
(V4-only, no V3 equivalent at all) and `health` (V3's `/health` isn't
versioned either, already shared) need none. Tag each `/V3.0/` wrapper
distinctly (`"SIC (V3.0, alias)"`, etc.) so Swagger UI's sidebar groups
the legacy paths visibly apart from the primary `/V4.0/` ones, the same
way V3's own `/docs` already separates `"... (V3.0, legacy v1)"` from
the default tag.

## 9. Open questions

**None — built, verified live, nothing left outstanding.** Both real
design choices this plan raised (typed vs. generic response schemas
§1, alias scope/documentation depth §8) were decided before
implementation; the two real bugs implementation itself surfaced
(`routes!` bundling, duplicate `paths(...)`) are fixed and documented
in §0/§3.3 for the next person who reaches for `utoipa-axum`.
