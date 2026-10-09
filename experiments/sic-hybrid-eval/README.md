# sic-hybrid-eval

Regression check for hybrid (keyword + semantic, Reciprocal Rank Fusion) SIC
search, `GET /V4.0/global/sic/hybrid/{query}`. Method and rationale:
`docs/plans/sic-hybrid-search.md` sections 3 and 5.

* `concepts.json` - 37 hand-picked concepts, each with three query forms (short
  phrase, long sentence, single term) and the acceptable class ids in each of
  the four systems. Picked by one author from class text before any score was
  seen; the ISIC picks mirror the NACE ones through the shared four-digit code.
* `eval.py` - three commands:

```bash
# 1. feather -> JSON + raw float32 (needs pyarrow)
python3 eval.py dump  /path/to/company_dns/tmp  /tmp/sic-eval

# 2. the offline method (needs numpy + sentence-transformers; first run downloads the model)
python3 eval.py simulate /tmp/sic-eval

# 3. the live endpoints (stdlib only; server must be running with all four systems loaded)
python3 eval.py server /tmp/sic-eval http://127.0.0.1:4000
```

`simulate` and `server` print the same table (any@1 / any@3 / any@10 / MRR /
pair@10 per query form) and exit 1 if a threshold fails:

* single-term queries: hybrid any@10 >= .95 and hybrid MRR >= semantic MRR;
* short phrases: hybrid MRR no more than .08 below semantic;
* long sentences, when keyword finds nothing: hybrid must score identically to
  semantic (compared as ordered similarity scores, because identical rows in two
  systems tie exactly and may swap places).

Why three commands: on the machine this was written on, pyarrow and
numpy/sentence-transformers live in different Python installs, so `dump` is the
only step that needs pyarrow and the others read its output. The data files are
the four `*_flat_embedded.feather` files in the repo's top-level `tmp/`; the
server must have been started on the same files. The script identifies itself
with a User-Agent because the server returns 429 to anonymous ones.

Reference result (2026-10-04): single terms hybrid any@10 1.00 vs semantic .86,
MRR .82 vs .70; long sentences identical; short phrases within .04 MRR.
