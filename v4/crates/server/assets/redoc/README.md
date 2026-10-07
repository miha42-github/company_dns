# Vendored Redoc (self-hosted API reference)

`redoc.standalone.js` is Redoc **2.5.4**, the unmodified standalone bundle from Redocly's CDN,
vendored so the `/redoc` page needs no third-party request (no CDN, no Google Fonts) and works on
isolated networks. It is embedded in the server binary and served at `/redoc/redoc.standalone.js`
(`crates/server/src/docs.rs`).

| | |
|---|---|
| Source | `https://cdn.redoc.ly/redoc/v2.5.4/bundles/redoc.standalone.js` |
| SHA-256 | `dcaf76612bc4a3fbcc923a8966dee2f6146a5f32e5ce1b6f02dd60cbbf89500b` |
| Size | 1,103,471 bytes |
| Licence | MIT, (c) 2015-present Rebilly, Inc. (`LICENSE`) |
| Bundled third-party code | React, Prism, DOMPurify, and others; notices in `redoc.standalone.js.LICENSE.txt` |

A test in `docs.rs` pins the SHA-256, so the file cannot change without someone deciding to.

To upgrade: download the new version's `bundles/redoc.standalone.js` and its `.LICENSE.txt`, replace the
files here, update the version and hash above and in the test, and check `/redoc` in a browser.
The licences must stay next to the file and ship with any image or release that contains it.
