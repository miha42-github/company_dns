# Third-party notices (V4 server)

The V4 server embeds the following third-party front-end assets in its binary. They are served as-is;
none is modified. Rust dependencies are listed by `cargo` (see `Cargo.lock`) and carry their own licences.

## Redoc 2.5.4 (the `/redoc` API reference page)

- Files: `crates/server/assets/redoc/redoc.standalone.js`, with the licence texts in `crates/server/assets/redoc/LICENSE` and
  `crates/server/assets/redoc/redoc.standalone.js.LICENSE.txt`, and provenance in `crates/server/assets/redoc/README.md`.
- Licence: **MIT**, Copyright (c) 2015-present, Rebilly, Inc. https://github.com/Redocly/redoc
- Bundled in that file, with notices preserved in `redoc.standalone.js.LICENSE.txt`:
  React, react-dom, scheduler, use-sync-external-store, react-is (MIT, Facebook/Meta);
  Prism (MIT, Lea Verou); classnames (MIT, Jed Watson); Stickyfill (MIT, Oleg Korsunsky);
  perfect-scrollbar (MIT, Hyunje Jun and MDBootstrap); mark.js (MIT, Julian Kuhnel);
  DOMPurify 3.4.13 (Cure53; offered under Apache-2.0 or MPL-2.0, used here under Apache-2.0).

## Swagger UI (the `/docs` API explorer)

- Embedded by the `utoipa-swagger-ui` crate (licensed MIT OR Apache-2.0), which bundles the Swagger UI distribution at build time.
- Licence: **Apache-2.0** (the Swagger UI project, https://github.com/swagger-api/swagger-ui). The Apache-2.0 text and notice ship inside that distribution.

## Fonts

None. The API reference pages use the system font stack; no web fonts are loaded or embedded.

Anyone redistributing the server (a binary, a container image, or a source archive that includes `crates/server/assets/`) must
keep this file and the licence files above with it.
