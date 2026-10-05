# company-sic-eval

Development-side evaluation for the company -> industry-code match
(`docs/plans/company-sic-match.md`, sections 3 and 8). It exists to settle chunk
size, scoring and (later) model choice with numbers instead of argument.
Not product data: nothing from users goes in here, and the stepper's session
choices are never stored (plan decision 7).

* `names.txt` - the companies, mixed large and small so short, medium and long
  descriptions are all represented. Companies the Wikipedia endpoint cannot
  resolve to a CIK are skipped (GE, Netflix, PayPal, Duolingo, Kellogg and
  Harley-Davidson came back "Unknown"; Mattel returns two CIKs).
* `companies_pool.json` - everything `build_dataset.py` resolved (399
  companies). `select_set.py` picks the 200 evaluation companies from it,
  stratified by description length (40% long, 32% mid, 28% short) and
  round-robin over SIC divisions, with a short `EXCLUDE` list of wrong
  Wikipedia matches.
* `companies.json` - the 200 chosen companies, one record per company: `name`, `cik`, the Wikipedia
  `description` snapshot, `filer_sic` and `filer_sic_description` **as filed
  with the SEC** (public submissions API, not from memory), plus `acceptable`
  (hand-judged acceptable codes per system, empty until we fill them) and
  `notes`. Records are plain JSON so mediumroast.io can append to the set
  later (plan decision 8).
* `chunker.py` / `test_chunker.py` - the sentence-window chunker the Rust port
  must match.
* `draft_labels.py` - writes the DRAFT `acceptable` sets (37 companies; US SIC,
  ISIC Rev.4, NACE Rev.2; validates each code against the feathers). Labels
  are `draft` until a human reviews them with `review.py` (all 37 are now `reviewed`). Japan SIC is not
  drafted yet.
* `review.py` - `make`/`apply` a plain-text review sheet (`review.md`) so the
  acceptable sets are judged by a person, not by the drafter.
* `select_eval.py` - compares rules for choosing the 2-5 recommended codes
  (top-N, similarity gap, per-chunk nominees) on the reviewed sets.
* `live_set_eval.py` - scores the running `POST /V4.0/global/sic/match`
  against the reviewed sets (set vs pool precision/recall/hit).
* `parity_check.py` - the Rust chunker must equal `chunker.py` on every
  description (200/200 at target 64).
* `crosswalk_eval.py` - can one system's codes find the matching codes in another
  (ISIC<->NACE identical-code check; US SIC pivot into ISIC/NACE vs matching the
  description directly; plan section 11).
* `eval.py` - `dump` (pyarrow, US/ISIC/NACE corpora to JSON) and `run` (numpy +
  sentence-transformers; sweeps chunk size x scoring, reports paired-bootstrap
  intervals; the second table scores the hand-drafted acceptable sets per system).

```bash
python3 build_dataset.py http://localhost:4000        # refresh descriptions + filer SIC (keeps your labels)
python3 test_chunker.py
arch -x86_64 python3.11 select_set.py --size 200      # re-pick from the pool (carries labels over)
python3 eval.py dump /path/to/company_dns/tmp /tmp/ceval
python3 eval.py run  /tmp/ceval                        # see the docstring for flags
```

The two Python installs differ on the machine this was written on (pyarrow vs
numpy/sentence-transformers), hence two commands, same as `sic-hybrid-eval`.
The server needs a self-identifying User-Agent or it answers 429.

Caveats that matter when reading the numbers: the filer SIC is one code chosen
by the filer, so it is a weak label; 61 of 200 filer codes are not 4-digit leaves
in the US corpus (for example 3570, 2080, 5810, 5200) and are scored only at
group/division level; at N=200 differences under about 0.06 are noise. (At N=44 a +9 point gain looked borderline and vanished at 200.)
