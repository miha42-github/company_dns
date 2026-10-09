# Company to industry-code match: long descriptions, chunking, merging, and the UX

Status: **Draft (2026-10-04). A first Industry Match tab is built (section 10); a simpler pivot design is proposed (section 11) and awaiting decisions.**
Decided (section 0): POST for pasted text; no LLM, limitations stated openly;
lives in the Company Explorer's Industry Match tab; description sources;
per-system answers; reading view first then a refining stepper; user choices
are session-only; English-only mode. Still open: chunk size/scoring (the
harness settles it).
Owner: michael.hay@mediumroast.io
Scope: given one company (by name, or by pasted description), return the
industry codes that best describe it, across the registered systems (US SIC,
Japan SIC, EU NACE Rev. 2, ISIC Rev. 4), and help the user reach a conclusion
about them. Out of scope: bulk/batch classification, training or fine-tuning a
model, any non-SIC data.
Related: `ic-similarity-search-poc.md` sec. 5.8 (silent truncation found) and
sec. 10 (first chunking sketch, which this doc replaces and corrects),
`sic-global-search.md`, `sic-hybrid-search.md`, `company-dns-ux.md` sec. 10.3,
`go-duckdb-rewrite.md` sec. 1 (single-company, reference-project intent).

---

## 0. Decisions made (2026-10-04)

1. **POST is fine for pasted text.** The match endpoint takes the text in a
   request body. This is a deliberate exception to V4's GET-only habit,
   because a 100-650 token description (up to about 4 KB) does not belong in a
   URL path. The by-name convenience stays a GET.
2. **No LLM, and we say so.** The core is retrieval, chunking, merging and
   human judgement. We do not hide what that costs: the limitations are
   stated in the product (section 5.5), not buried in this doc.
3. **Home: the Company Explorer's Industry Match tab.** The Company Explorer
   becomes `Merged | EDGAR | Wikipedia | Industry Match`. The Home page's
   existing Industry Match pill already points at "Industry Match"; it will
   land on this tab instead of jumping into the IC Semantic panel. The Merged
   card gets a link that opens the tab with the company already loaded.

4. **Description sources: both, and a text box the user controls.** The
   description can come from the merged/Wikipedia lookup (the company's own
   reporting where available) **and/or** text the user types or pastes. That
   needs real text boxes: the Home page's company box must be expandable
   (grows to several lines, or an expand control), and the Industry Match tab
   gets a large editor of its own (roughly a paragraph-and-a-half visible, with
   the live token/chunk meter beside it). When both exist, the user chooses
   which to use, or combines them; the response records which sources fed the
   match. Wikipedia is not always right or present, which is why pasting is
   first-class, not a fallback.
5. **Answers are per system.** (Refined 2026-10-04, section 11: US SIC is decided first, the other systems are mapped from it.) The point of having every system in one place
   is that the customer decides which code and class is relevant to each
   system and country. No blended cross-system list. Compare-style
   side-by-side is a display of the per-system answers (section 5.2).
6. **Reading view first, then a stepper to refine.** (Revised 2026-10-04: the four-step stepper was too much for a business user; section 11 proposes one page in two phases and keeps the reading view as a collapsible "how we read your text".) The reading view grounds
   the user (what the model saw, which chunk drove which code); a guided
   step-through then refines the result. The stepper is not the entry point
   (section 6, U1 then U2).
7. **User choices are session-only.** What the user does in the stepper
   (switching chunks off, picking sectors and codes) lives only in the working
   session and is not stored or used as training or evaluation data. See the
   consequence for tuning in section 8.
8. **A small developer-side evaluation set is kept** (a few dozen companies we
   judge ourselves, plus filer SIC), in the experiments folder. It is separate
   from user data. Later, when mediumroast.io integrates, growing this set from
   its data is a value-added feature; this plan only needs the set to be easy
   to extend (plain files, one record per company, documented format) so that
   integration is additive.
9. **The product answer is a recommended SET of codes, never a single code.**
   One code per company is the flaw in EDGAR and in other public-market
   registries: a filer picks one code, mostly by primary revenue, so a
   multi-line company is described by whichever line is largest (Domino's
   files as wholesale groceries; in our own data Apple, Costco and Caterpillar
   all sit far from their filed code). Industry Match returns a small
   recommended set per system, grouped by line of business, with the reason
   for each (which chunk and which sentence), and presents the company's
   filed SIC, when we have it, as one input beside ours rather than the
   answer. Consequences: no "the code is X" wording anywhere in the endpoint
   or UI; the endpoint has no `code` field, only `recommended` (the set),
   `alternatives` and `limitations`; and evaluation is set-based (any
   plausible code in the top k, recall of the plausible set), not top-1
   agreement with the filed code.
10. **English mode only for every system.** All four systems are supported, but
   matching runs against English labels with an English model. Non-English
   input is out of scope; the UI says so (section 5.5) rather than guessing.

---

## 1. The problem, with measurements

Today the Home page's **Industry Match** pill passes a company description to
the semantic search as one string. The embedding model reads only the first
256 word pieces and silently drops the rest. `ic-similarity-search-poc.md`
5.8 found this with IBM (469 tokens, the quantum/AI paragraph never seen);
the question here is how big the problem is and what to do about it. I
measured it rather than guessing.

### 1.1 How long are real descriptions?

Wikipedia lead descriptions for 42 well-known US companies (fetched through
our own `GET /V4.0/global/company/wikipedia/firmographics/{name}`), tokenised
with the model's own `tokenizer.json` (no truncation):

| Measure | Value |
|---|---|
| Median / p75 / p90 / max | 320 / 462 / 481 / 653 tokens |
| Longer than 256 (silently truncated today) | 27 of 42 (64%) |
| Longer than 512 (model's hard position limit) | 5 of 42 (12%) |
| Mean share of text the model never sees | 22% |
| Tokens per word | about 1.37 |

Caveats: the sample is large caps, which have the longest Wikipedia articles;
small and private companies will skew shorter, and EDGAR gives us no
description at all. Treat 64% as "most of the companies people will try first",
not as a population statistic.

### 1.2 Which text is lost matters more than how much

Wikipedia leads are mostly chronological: origin story first, current business
last. Truncation keeps the history and drops the present. That is exactly why
IBM matched "Calculating and Accounting Machines" (1911 punch-card tabulators)
instead of anything about its current business.

### 1.3 The targets are tiny; the queries are not

Token length of the text we embed for each classification entry
(`embedding_text`, a breadcrumb such as "Manufacturing > Electronic Equipment >
Semiconductors"), per system:

| System | Rows | Median | p90 | Max |
|---|---|---|---|---|
| US SIC | 1,005 | 24 | 34 | 57 |
| Japan SIC | 1,460 | 26 | 41 | 67 |
| NACE Rev. 2 | 615 | 28 | 43 | 76 |
| ISIC Rev. 4 | 419 | 28 | 42 | 76 |

So we compare a 100-650 token query against 25-token labels. The literature
calls this the query-document size imbalance and notes that embeddings favour
similarly-sized text. It argues for **chunks sized near the target**, not
chunks that merely fit the window (the earlier sketch in
`ic-similarity-search-poc.md` 10.1 proposed ~200 tokens; that is probably too
large, see 4).

---

## 2. External research

**The model's real limits.** The `all-MiniLM-L6-v2` card says input longer than
256 word pieces is truncated, and that the sequence length used in training was
limited to 128 tokens. The tokenizer config advertises 512 (and ours reports
`model_max_length` 256 in `tokenizer.json`), which is why some frameworks accept
longer input and cut it quietly. Quality also degrades as text approaches the
window. So there are two thresholds: a hard one at 256 and a soft one near 128
where the model was actually trained.
([model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2))

**Long-context alternatives exist and are in our embedding crate.** The
`fastembed` 7.1.0 catalogue includes Nomic Embed Text v1/v1.5 (8192 context),
BGE-M3 (8192, multilingual), GTE-base/large-en v1.5 (8192) and ModernBERT
Embed Large, next to the MiniLM family we use. Our corpus vectors are MiniLM
(`vector_all_minilm_l6_v2`), but the corpus is only 3,499 short strings that
already sit in the feather as `embedding_text`, so re-embedding it with another
model is cheap and does not need a new Mediumroast delivery. The endpoints
already take a `model` parameter. A bigger window removes truncation, but it
does not by itself remove the multi-topic problem (one vector for a company
that is genuinely about several things), and Nomic-style models want
`search_query:` / `search_document:` prefixes. (Model list read from the crate
source in the local cargo registry.)

**Chunking and pooling.** The standard practice is to split, embed each chunk,
then aggregate by mean, max or weighted pooling. Mean pooling blends topics;
the late-chunking paper (embed the whole text with a long-context model, then
pool per chunk) reports about +1.5 to +1.9 nDCG@10 on average over naive
chunking on BEIR, but it needs a long-context model and it optimises
retrieval of passages that need document context, which is not our shape (our
targets are short labels with no surrounding document).
([Late Chunking, arXiv 2409.04701](https://arxiv.org/html/2409.04701v3);
[Jina write-up](https://jina.ai/news/late-chunking-in-long-context-embedding-models/))

**Industry-classification systems already built this way.** The pattern is
consistently two-stage: embedding retrieval of candidates, then a decision
step.
- ONS **ClassifAI**: MiniLM embeds the SIC descriptions and the free text,
  then a general LLM picks among candidates, returns likelihoods and
  reasoning, and can say "uncodable" with a follow-up question. They report
  only a marginal accuracy gain over a logistic-regression baseline at 2- and
  5-digit SIC, strongest on jargon and context-dependent text, and call it
  experimental.
  ([ONS Data Science Campus](https://datasciencecampus.ons.gov.uk/classifai-exploring-the-use-of-large-language-models-llms-to-assign-free-text-to-commonly-used-classifications))
- US Census **BEACON** (NAICS autocoder): predicts hierarchically (2-digit
  first, then 6-digit), uses ensembles, trained on 3.7M records, and returns a
  *list of candidates for the respondent to choose from*, not a single answer.
  ([Census working paper](https://www.census.gov/library/working-papers/2024/econ/industry-self-classification-in-the-economic-census.html);
  [FCSM 2023 slides](https://www.fcsm.gov/assets/files/docs/2023-conference-docs/A5.1_Whitehead.pdf))
- Ramp and others describe the same retrieve-then-select shape
  ([search result summary](https://www.zenml.io/llmops-database/rag-based-industry-classification-system-for-customer-segmentation);
  I could not read Ramp's own post, so I rely only on that summary).

Two things to take from this: hierarchical decisions are normal, and
production systems put a human or an LLM *after* retrieval. We have no LLM in
V4 and the project is a reference implementation; the human-in-the-loop path
is the natural fit (see 5.4 and 6).

**The ground truth is itself weak.** SEC SIC codes are self-selected by the
filer, mainly by primary revenue, and a company gets one code even if it spans
several. Domino's Pizza files under wholesale groceries rather than eating
places; the SIC system under-represents modern tech.
([The Corporate Counsel](https://www.thecorporatecounsel.net/blog/2016/03/sic-codes-how-does-the-sec-assign-them.html))
So "does our top result equal the SEC code" is a noisy yardstick, and any
accuracy figure we publish needs that caveat.

**UX guidance for steppers.** Multi-step flows suit tasks that are sequential,
where each step builds on the last, and where input needs validation; they are
a poor fit for short forms or when users revisit sections often. Progressive
disclosure is the principle behind them.
([general guidance summary](https://uxplanet.org/how-to-design-a-magical-form-wizard-e0c6458f6318);
I could not retrieve Nielsen Norman Group's own pages through search, so the
design discussion in 6 leans on these generic sources and on our own
constraint that the fast path must stay one click.)

---

## 3. Pilot: does chunking raise accuracy? (small, honest, inconclusive)

I ran a throwaway experiment (scratch script, not in the repo yet) to find out
whether the chunking strategies in 4 change results before we design around
them. 24 companies, US SIC corpus only, the stored MiniLM vectors, scored
against the filer-reported SEC SIC code. **The "truth" codes were written from
memory and are unverified**; several (IBM 3570, GE 3600, 3M 3290, Lockheed
3760, P&G 2840, Alphabet 7370) are group-level or absent from the 4-digit US
corpus, so those rows could only ever score "same 3-digit group".

Strategies: *trunc256* is today's behaviour. *chunkN_max* packs whole
sentences up to N tokens (one sentence of overlap), embeds each chunk, takes
the best similarity per corpus row across chunks. *meanvec* averages the chunk
vectors. *top3mean* averages each row's three best chunk scores.

| Strategy | exact @1 | @3 | @5 | @10 | same 3-digit group @5 |
|---|---|---|---|---|---|
| trunc256 (today) | 1 | 4 | 8 | 8 | 12 / 24 |
| chunk64 max | 3 | 6 | 8 | 9 | 10 / 24 |
| chunk128 max | 2 | 2 | 7 | 10 | 11 / 24 |
| chunk200 max | 2 | 6 | 10 | 10 | 14 / 24 |
| chunk128 mean vector | 1 | 4 | 6 | 8 | 9 / 24 |
| chunk128 top-3 mean | 2 | 4 | 7 | 8 | 11 / 24 |

Chunks per company at 64 / 128 / 200 tokens: 4-14 / 2-7 / 1-4.

What this does and does not show:

1. **No strategy clearly wins.** The spread (8 to 10 hits at @10) is inside the
   noise of 24 companies. Chunking is not demonstrably a free accuracy gain
   on a single "does it equal the SEC code" measure.
2. **Mean-of-chunk-vectors is no better than truncation**, which supports the
   earlier decision (`ic-similarity-search-poc.md` 10.1) to reject averaging.
3. **Where it helps is visible per company, not in the totals.** Starbucks went
   from rank 37 (truncated) to 8 (128 max) to 4 (200 max); Intel and Chevron
   improved; Apple, Costco and Caterpillar got worse or stayed far down in every
   strategy because their filed SIC (3571 electronic computers, 5399 misc.
   retail, 3531 construction machinery) is a narrow reading of a broad
   business that the descriptions do not emphasise.
4. **Realistic expectation to set with users:** against filer SIC codes the
   exact 4-digit code lands in the top 10 roughly 33-42% of the time and the
   right 3-digit group in the top 5 roughly 38-58% of the time, for any
   strategy tested. Much of the remaining gap is label noise and "Not
   Elsewhere Classified" classes, not retrieval failure.

**Update (2026-10-04, later): the table above is superseded by a run with
verified labels.** My memory-written "truth" codes were wrong for several
companies (Coca-Cola files under 2080, Starbucks 5810, Nike 3021, 3M 3841,
Honeywell 3724, Disney 7990), so the pilot's absolute numbers were
understated. `experiments/company-sic-eval` now pulls the filer SIC from the
SEC's submissions API for 44 companies and sweeps chunk size 64-200 with a
paired bootstrap. Findings:

- Baseline (today's truncation): exact 4-digit in top 10 **47%** (of the 32
  companies whose filer code is a leaf in our corpus), right 3-digit group in
  top 5 **48%**, right 2-digit division in top 3 **59%**.
- **Max-pool chunking at 128 or 200 tokens: group@5 57%, +9 points over
  truncation, 95% interval about [0, +0.20].** Borderline, not proven.
  On descriptions over 256 tokens (n=25) group@5 goes 60% to 72%; on
  shorter ones it does not change, as it must not.
- **Vote (RRF across chunks) and mean-vector are no better than truncation**
  and vote is sometimes worse. Max-pool stays the working scoring; mean-vector
  stays rejected.
- **Chunk size:** 64 shows nothing; 128 and 200 are indistinguishable at this
  N. 128 remains the default, as the model was trained there, but the data
  does not choose between 128 and 200.
- None of the deltas is significant at N=44. A decision between 128 and 200
  needs a larger set (the plan's ~200 companies) or the hand-judged acceptable
  sets, which count a plausible code as correct.

**Update 2 (2026-10-04, N=200): the borderline gain above did not hold.**
`companies.json` now has 200 companies (80 long, 64 mid, 56 short
descriptions; 53 SIC divisions; the 399-company pool is kept in
`companies_pool.json`). Same sweep, same verified filer SIC:

- Truncation baseline: exact 4-digit in top 10 **56%** (of the 139 companies
  whose filer code is a corpus leaf), group@5 **46%**, division@3 **65%**.
- **No strategy beats truncation by a meaningful margin.** The group@5
  deltas for every chunk size and scoring method sit between -0.09 and +0.06
  and their intervals straddle zero (vote160 is slightly worse). The best
  single cell, max-pool at 200 tokens, is +0.04 on exact@10 with an interval
  of [0.00, +0.08]. On long descriptions (n=80) group@5 goes 55% to 60%;
  on short and mid ones it is unchanged. The N=44 "+9 points" was noise.
- Reading: against the filer-SIC yardstick, chunking neither helps nor hurts
  accuracy. That fits the pilot's conclusion below, and it makes the
  yardstick the problem: filer SIC is one code per company and cannot reward
  surfacing a second line of business or explaining a match.

**Consequence for the plan:** do not justify chunking by accuracy against
filer SIC. Justify it by coverage and explainability, and measure those with
the hand-judged `acceptable` sets (any plausible code in the top k, lines of
business covered). Until those exist, chunk size stays at the 128 default and
max-pool stays the scoring; neither is supported by a measured advantage.

**Update 3 (2026-10-04): the hand-drafted acceptable sets, now human-reviewed.**
All 37 were reviewed on 2026-10-04 (`labels_status: "reviewed"`); the review
removed 12 codes across 8 companies, mostly financing arms and payment-network
services I had been too generous with (Ford and Caterpillar credit, Visa 7389,
Live Nation ticketing, P&G razors). Rerunning on the reviewed labels left every
conclusion below unchanged (US SIC any@10 still 0.68 vs 0.78; recall@10 moved
0.39 to 0.40 and 0.47 to 0.49). Original draft wording follows.
`companies.json` now carries `acceptable` codes (US SIC, ISIC Rev.4, NACE
Rev.2) for 37 companies, status `draft`. I wrote them from each company's lines
of business, not from retrieval, and checked that every code exists in its
corpus (`draft_labels.py`). NACE is listed separately because its four-digit
classes are not always ISIC's (pharmaceuticals is 21.10/21.20 in NACE, 2100 in
ISIC). Results (any plausible code in the top 10):

| System | truncation | max-pool 128 | max-pool 200 | delta vs truncation (95% CI) |
|---|---|---|---|---|
| US SIC | 0.68 | **0.78** | 0.73 | max128 [+0.03, +0.22]; max200 [0.00, +0.14] |
| ISIC Rev.4 | 0.89 | 0.81 | 0.86 | max128 [-0.22, +0.03] |
| NACE Rev.2 | 0.86 | 0.81 | 0.84 | max128 [-0.16, +0.05] |

Recall of the plausible codes in the top 10 follows the same pattern (US 0.39
to 0.47 with max-pool; ISIC and NACE flat at about 0.56-0.59). Reading it
honestly:

- **A real but small signal for US SIC only.** Chunking helps surface plausible
  US codes, which are fine-grained (1,005 classes) so a long multi-topic
  description has many places to land. ISIC and NACE have fewer, broader
  classes and truncation already finds one; chunking does not help and may
  cost a little.
- **N=37 and one labeller.** Intervals are wide, I wrote the labels, and the
  37 were chosen as well-known multi-line businesses. Treat this as a
  hypothesis for the 128-token max-pool default, not a result.
- **Vote and mean-vector remain no better than truncation.**
- Needed next: a human review of the drafts (that is the point of the
  `draft` status), and enough companies labelled (target 80+) to tell a
  per-system effect from noise.

**Conclusion for planning:** chunking's value is *coverage and explainability*
(surface several lines of business, show which sentence drove which code, stop
losing the current business), not a large lift in top-1 accuracy. That changes
how we should judge it: by whether a reasonable code appears among the
candidates and the user can see why, not by matching one SEC code. It also
means we need a better evaluation set before tuning anything (see 8).

---

## 4. Chunking strategy (proposals)

| # | Strategy | Idea | Notes |
|---|---|---|---|
| A | Truncate | Today. Model sees first 256 tokens | Loses the present business; keep only as the baseline in the harness |
| B | Head + tail | First N and last N tokens | Cheap, but arbitrary; Wikipedia's tail is not reliably the business summary |
| C | Sentence windows | Pack whole sentences to a target size, one-sentence overlap | Simple, deterministic, explainable; the working proposal |
| D | Topic segmentation | Start a new chunk where adjacent-sentence similarity drops (TextTiling-style) | Chunks follow topics, not length; more moving parts, still deterministic |
| E | Per sentence | Every sentence a chunk | Best fit to 25-token targets; most calls, noisiest on short sentences |
| F | Late chunking | Embed whole text with a long-context model, pool per chunk | Needs a model swap (2, 7); built for passage retrieval, so uncertain fit |

**Working proposal: C, target about 100-128 tokens, hard cap 200.** Reasons:
the model was trained at 128, the labels are about 25 tokens, and the pilot
could not tell 64, 128 and 200 apart, so the size should be a parameter that
the evaluation harness settles, not a number we hard-code on instinct. A short
description (under about 128 tokens) is a single chunk and takes the exact
same path as a long one, so there is no special case.

Details to settle:
- **Sentence splitting.** The pilot used a punctuation regex; Wikipedia text
  has abbreviations ("Inc.", "U.S.") and parenthetical dates that break naive
  splits. Needs a small rule set or a proper segmenter, and tests against real
  descriptions.
- **Overlap.** One sentence, but only if it is under half the target, so
  overlap cannot dominate a chunk.
- **Noise chunks.** Founding dates, headquarters, stock listings, awards and
  legal history carry little industry signal and will happily match "Legal
  services" or "Security brokers". Options: a small stop-pattern list; down-
  weighting chunks whose best similarity is low; or letting the user switch
  them off (see 6). Prefer the last two over a rule list that rots.
- **Lead sentence.** The first sentence of a Wikipedia lead ("X is an American
  multinational technology company...") defines the entity and deserves extra
  weight at the sector level. Decide whether that is a rule or something the
  evaluation shows we need.
- **Cap and cost.** The pilot's 42 descriptions gave at most 7 chunks at 128
  tokens. Cap chunks per request (say 16) and refuse beyond that with a clear
  message. Per-chunk embedding latency is **not measured yet**; measure before
  promising an interactive budget.
- **Keep the token check.** The live `/V4.0/na/sic/similarity-check` meter stays
  useful, but its meaning changes from "will be truncated" to "will be split
  into N chunks".

Note on the existing hybrid search: its keyword half is a substring match of
the query inside class descriptions, which can never match a pasted paragraph.
For long text the Combined tab degrades to semantic-only (it already shows a
note when keyword finds nothing). The chunked path should be semantic per
chunk; any keyword help would have to come from extracting distinctive terms,
which is a separate idea and not proposed here.

---

## 5. Per-chunk matching and the merge strategy

### 5.1 Per chunk

Embed each chunk, search all registered systems (the existing global
`UNION ALL` path in `crates/sic/src/global.rs`), keep the top N per chunk
(N about 10) with the chunk index and similarity.

### 5.2 Merge into one answer: three layers

1. **Entry level.** Group hits by `unique_key`. Two candidate scorings, to be
   compared in the harness rather than chosen by argument:
   - **Max-similarity:** an entry's score is its best chunk similarity
     (already decided in `ic-similarity-search-poc.md` 10.1 over averaging).
     Easy to explain, but similarities are not on the same scale across
     systems (measured offsets in `sic-global-search.md`: ISIC about -0.06,
     NACE about -0.04 against US).
   - **Chunk voting (RRF across chunks):** each chunk's ranking contributes
     `1/(k + rank)` to an entry, the same fusion `hybrid.rs` already
     implements. Immune to cross-system scale offsets and rewards entries
     that several chunks agree on.
   Either way, keep three things per entry for display: best similarity,
   **support** (how many chunks put it in their top m), and the **best chunk's
   text** as the "matched on" evidence.
2. **Hierarchy roll-up.** Roll leaf hits up to division/group and sum support
   per node. This is the BEACON idea (decide coarse first, then fine) and the
   most robust signal we have: the pilot's same-group hit rate (38-58%) is
   better than the exact-code rate (33-42%), so the coarse answer is more
   reliable than the leaf. Present "most likely sector" before "most likely
   code".
3. **Per system, not one blended list.** Return an independent answer for each
   system. Users mean "SIC" or "NACE" or "ISIC", and mixing them hides which
   one an entry belongs to. A cross-system view is a display choice
   (show the same company in each system side by side), not a merge.

### 5.3 Multiple codes and confidence

This is decision 9 in section 0 made concrete: the unit of output is a
recommended set, so everything below (primary and secondary, lines of
business, confidence) describes how that set is built and shown.

- **Primary vs secondary.** Return a small primary set per system (cap 3)
  and a longer secondary list, grouped by line of business (group chunks by the
  division their best entry rolls up to). IBM should be able to come back with
  computer hardware, software and IT services, not one forced winner.
- **Confidence is a few signals, not one number:** the best similarity mapped
  through the calibrated labels already in the UI (Unlikely / Possible /
  Likely, `ic-similarity-search-poc.md` 5.7), the margin to the runner-up, and
  support (chunks in agreement). Show them; do not collapse them into a
  made-up percentage.
- **"Cannot tell" is a valid answer.** If every chunk's best similarity is
  low, or only noise chunks exist, return that and ask for more text rather
  than a confident wrong code (ClassifAI's "uncodable" state).

### 5.4 Endpoint, UX, or both?

Both, and the split is the proposal: the **endpoint is deterministic and
structured** (chunks, per-chunk candidates, per-system rolled-up answer,
confidence signals, evidence) so a script gets the same answer a person sees;
the **UX is where judgement happens** (switching chunks off, picking among
close candidates, overriding the sector). No LLM in the loop (decision 2 in
section 0).

Sketch only, shapes not final:

```
POST /V4.0/global/sic/match            body: { "text": "...", "options": { chunk_target, top_n } }
GET  /V4.0/global/company/{name}/sic-match     (resolves description via the merged endpoint, then as above)

data: {
  input:   { source: "wikipedia|pasted", tokens, chunks: n, truncated: false },
  chunks:  [ { i, text, tokens, noise: bool, top: [ {unique_key, source_type, sim} ] } ],
  systems: { us_sic: { sectors: [...], recommended: [ {code, line_of_business, evidence_chunk, sim} ], alternatives: [...] }, nace_rev2: {...}, ... },
  filed:   { us_sic: "3571" } | null,      // the company's own filing, shown beside the set, never as the answer
  limitations: [ ... ],
  confidence: { label, best_sim, margin, support },
  note:    "cannot tell: ..." | null
}
```

POST for the text is decided (section 0). Remaining API questions: whether the
by-name GET is worth having given the UI can call the merged endpoint and then
POST (cheap to keep, but it is a second contract to maintain), whether the POST
needs the same rate-limit tier as the cheap GETs (it embeds several chunks per
call, so it is the most expensive endpoint V4 would have), and a maximum body
size.

### 5.5 Stating the limitations (no LLM means these are real)

Without a model that reads and reasons, we are matching meaning by vector
similarity to short labels. We should say plainly where that breaks, in the
response (a `limitations` array of short codes plus a one-line explanation)
and in the UI (a collapsible "How to read this" panel, and an inline notice
when a specific limitation applies to the current result):

- **Not a decision, a ranked suggestion.** Results are candidates. Even a
  "Likely" label means "similar wording", not "this is the company's code".
- **Wording, not facts.** Embeddings match how a description reads. A
  company that never mentions what it sells, or mentions it in unusual words,
  will match poorly; marketing language matches marketing-adjacent classes.
- **No judgement about what matters most.** The method cannot tell the main
  business from a side line. Support and position are only proxies for
  primary activity. (A reader or an LLM could weigh the revenue mix; we
  cannot.)
- **History leaks in.** Old business (IBM's tabulators) can match a code
  that is no longer relevant; the noise/low-signal chunk flag is a heuristic,
  not understanding.
- **Single-company-label problem.** Filers choose one SIC, mostly by primary
  revenue, so our answer and the filed code can legitimately differ (the
  pilot shows large misses such as Apple and Costco).
- **Coverage depends on the text.** Under about 30-40 words there is not
  enough to say anything; the endpoint returns "cannot tell".
- **English only** for now (MiniLM and English labels).
- **Measured expectation.** Quote the evaluation numbers once we have them
  (pilot: exact 4-digit code in the top 10 about a third to 40% of the time,
  right 3-digit group in the top 5 roughly 40-60%), with their caveats.

Why this is acceptable: the project is a reference implementation of working
with IC and company data, and honest uncertainty is part of the lesson. The
response and UI should make "here is what the method cannot know" easy to
find, and the guided mode (section 6) gives the user the one thing the
algorithm lacks, which is their own judgement.

---

## 6. UX strategy

What we are designing around: input is ambiguous, the correct answer depends on
judgement, and the user needs to see *why* before they trust a code. A static
ranked list (today) answers neither. Ideas, from smallest to most novel, not
mutually exclusive:

**U1. Reading view (explain what the model saw).** Show the description with
each chunk visibly bracketed and coloured. A marker shows where the old
256-token window would have stopped (the 22% that used to vanish). Click a
chunk to see its top codes; click a code to highlight the chunks that support
it. Cheap, directly answers the confusion that started this, and is the
foundation for everything below.

```
 Company: International Business Machines   [479 tokens -> 7 chunks]
 +-------------------------------------+  +-------------------------------+
 | [1] IBM is an American multinational|  | Sector (US SIC)               |
 |     technology corporation ...      |  |  Services - Business  ####..  |
 | [2] Founded 1911 as Computing-...   |  |  Manufacturing - Industrial   |
 |  ---- old 256-token cutoff ----     |  | Codes                         |
 | [5] ... quantum, AI, hybrid cloud   |  |  7371 Computer programming ...|
 +-------------------------------------+  |  evidence: chunk 5, 0.62      |
                                          +-------------------------------+
```

**U2. Guided mode (the stepper).** The task is sequential and judgement-heavy,
which is the case where a stepper earns its place; it is a poor fit when the
user already knows what they want. So: a **Quick / Guided toggle**, Quick being
today's one-click result built on U1, Guided adding steps. Every step has a
sensible default so "Next, Next, Next" always works.

1. **Company**: name lookup, shows the description, token meter, editable text
   (trim, paste your own). Replaces the current free-for-all text box.
2. **Segments**: the chunks as cards, each with its top codes; switch off
   irrelevant ones (history, legal), merge or split. Real-time effect on step 3.
3. **Sector**: the hierarchy roll-up as a ranked list of sectors with support
   bars; pick one or more. Narrows the code choices.
4. **Codes**: per system, candidates within the chosen sectors, with evidence
   and confidence; mark primary/secondary.
5. **Result**: the chosen codes per system, copy / View JSON / export, and the
   reasoning trail (which chunks, which choices you made).

```
 (1 Company) -- (2 Segments) -- (3 Sector) -- (4 Codes) -- (5 Result)
       ^ always reachable; steps are skippable; state kept when you go back
```

Risks to design for: users revisit earlier steps often (general stepper guidance
says they handle that badly), so the stepper must be a **non-blocking
rail** where any step is reachable and changes ripple forward, not a locked
wizard; and it must not slow the expert path.

**U3. Candidate probing (borrowed from ClassifAI's follow-up question).**
When two sectors are near-tied, ask one plain question ("Does this company
make the products it sells, or resell them?") generated from the difference
between the candidates' labels, answered yes/no, which re-weights chunks. Needs
curated question templates per near-tie; promising, but only after U1 and U2
prove useful.

**U4. Visual alternatives (optional, probably later).** A chunk-to-sector-to-
code flow diagram makes multi-line businesses legible at a glance, and a
side-by-side per-system answer reuses the Compare layout. Nice, not needed to
learn whether the approach works.

**Fit with what exists.** The Company Explorer's Merged tab already builds the
company description and CIK; the IC explorer shell, calibrated labels and View
JSON modal are reusable. **Where it lives is decided (section 0):** the
Industry Match tab of the Company Explorer, in the same IC-style shell as
Merged, EDGAR and Wikipedia. Like the other tabs it carries the query when you
switch (type a name on Merged, switch to Industry Match, it loads that
company's description). Practical consequences: the tab's first step is the
company lookup (the existing merged endpoint supplies the description and
CIK); the `Home > Company > Industry Match` pill lands here; and the Compare
and Combined tabs in the IC explorer are not touched. The tab also needs a
paste-your-own-text path, because Wikipedia is not always right or present.

**Enrichment worth considering.** Show the company's own filed SEC SIC next to
our match ("filed as 3571; description suggests ..."). That frames the
disagreements we saw in the pilot instead of hiding them. EDGAR's SIC is not
in the 10-x catalog today (SIC data staging is manual, see
`v4-deployment.md`), so this is gated on data.

---

## 7. Model choice

Keep **MiniLM plus chunking** as the default: corpus vectors already match,
the chunking fixes the window, and chunk size can sit where the model was
trained. In parallel, run a **bake-off** in the harness because the corpus is
cheap to re-embed: MiniLM + chunks, Nomic v1.5 whole-text, Nomic + chunks,
BGE-M3 (also tests non-English), GTE v1.5. Whole-text on a long-context model
removes truncation but not multi-topic dilution, and may not beat chunking;
measure rather than assume. Anything needing prefixes must apply them to both
the corpus and the query path. Model swap also touches binary size and
container image (`v4-deployment.md`), a real cost for the thin-binary goal.

---

## 8. Evaluation plan

Before tuning anything. **Note (decision 7):** the stepper's user choices are
session-only and never stored, so they cannot double as an evaluation set.
Tuning chunk size, scoring and model therefore needs a small *developer-side*
set that is separate from the product: public data (the filer SEC SIC) plus a
few dozen companies we judge ourselves during development, kept in the
experiments folder, never collected from users. **Decided (2026-10-04): keep the
small hand-judged set** alongside filer SIC. Format should be extensible
(one JSON record per company: name, description source, filer SIC, acceptable
codes per system, notes) so mediumroast.io can later contribute and expand it.

1. **Build a better evaluation set.** About 200 companies, stratified by
   description length (under 128 / 128-256 / over 256 tokens) and by sector.
   Labels: the filer SIC pulled from SEC (to verify, not from memory as in
   the pilot), plus, for about 30-50, a hand-judged *set of acceptable codes*,
   because "one right answer" does not fit multi-activity companies.
2. **Metrics at several levels:** hit@k at 2-, 3- and 4-digit, "any acceptable
   code in top k", coverage of lines of business, and rate of confident-wrong
   (high confidence, wrong group), which matters more than top-1 here.
3. **Harness:** extend the `experiments/sic-hybrid-eval` pattern into
   `experiments/company-sic-eval`, bring the pilot script in from scratch,
   run strategy x chunk size x scoring (max vs voting) x model, with
   pass/fail thresholds only after we see baseline numbers.
4. **Regression in CI later,** same as the hybrid harness.
5. **Cost check:** per-chunk latency and total time for a 7-chunk company on
   the target hardware.

---

## 9. Open decisions (struck-through items are decided)

1. ~~**Description source.**~~ **Decided: merged/Wikipedia and user text,
   with expandable text boxes** (section 0).
2. ~~**POST for text.**~~ **Decided: POST** (section 0).
3. ~~**Per-system answers vs one global answer.**~~ **Decided: per system**
   (section 0).
4. ~~**LLM rerank/selection.**~~ **Decided: no LLM**, limitations stated
   openly (sections 0 and 5.5).
5. ~~**UX scope.**~~ **Decided: reading view first, then a stepper to
   refine** (section 0).
6. ~~**Where it lives.**~~ **Decided: the Company Explorer's Industry Match
   tab** (section 0).
7. **Chunk size and scoring** (leave to the harness) and whether to run the
   model bake-off before or after the first build.
8. ~~**Evaluation labels.**~~ **Decided for the product:** the user's
   stepper choices are session-only (section 0, decision 7). **Still open for
   development:** **decided** - we keep a small developer-side set (section 8),
   extensible later via mediumroast.io.
9. ~~**Non-English text and JSIC.**~~ **Decided: all systems, English mode
   only** (section 0). Japanese-language input is out of scope.

---

## 10. As built (2026-10-04) and what is next

The user asked to see the system in play before labelling more companies, with
the end of the stepper delivering **2-5 codes with their hierarchy**. So steps
2-4 of the earlier order were built as one vertical slice (not committed).

**Built**
- `crates/sic/src/company_match.rs`: sentence-window chunker (a port of
  `experiments/company-sic-eval/chunker.py`, byte-for-byte identical chunks on
  all 200 evaluation descriptions, `parity_check.py`), per-system search
  (`SicCatalog::search_per_system`: each system's own 50 nearest per chunk, so a
  system with lower similarities is not crowded out), and the selection rule
  `choose`. 8 unit tests; whole workspace tests and clippy clean.
- `POST /V4.0/global/sic/match` (the first POST route). Body `{text}` or
  `{chunks:[...]}` (re-match the segments you kept, nothing re-split). Returns
  `input`, `chunks` (each with its own top 3 per system and whether a plain
  search would have read it: `read`/`partial`/`unread`), `systems`
  (`recommended` 2-5 and `alternatives`, each with the full four-level
  hierarchy, similarity, votes and the evidence chunk) and `limitations`.
  Body limit 64 KB (existing layer), text up to 30,000 characters, at most 16
  chunks. About 70-145 ms per company on this machine.
- **The selection rule ("chunk winners"):** every chunk nominates its best
  codes (two, or more when there are few chunks, see below); codes rank by
  votes then best similarity; top 5, padded to the floor of 2. Every
  recommended code therefore has a chunk that supports it. Chosen over a plain
  top-5 and a similarity-gap rule in `select_eval.py` because it matches the
  multi-business idea and scored the same or better.
- UI: Company Explorer gets the fourth tab **Industry Match** (stepper: Company
  > Segments > Codes > Result, every reachable step clickable). Segments is the
  reading view (each segment, what it alone points at, a marker for the part a
  plain search would never have read, switch segments off and re-match). Codes
  has per-system pickers with a 2-5 counter, the hierarchy as a breadcrumb,
  similarity relative to the system's best, and the supporting segment. Result
  shows each chosen code with its section > division > group > class tree; copy
  as text, View JSON, start over. Home: the Company box is a growable textarea
  (Enter searches, Shift+Enter adds a line) and the Industry Match pill opens
  this tab with a name (description fetched) or a pasted description.
- Limitations are stated in the response and the tab ("How to read the results").

**What using it showed (and what changed because of it)**
1. **Short multi-business text gave only 2 codes.** A one-paragraph Hitachi
   description is one 128-token chunk, which nominates two codes. Fixed: chunk
   target 64 word pieces (nearer the ~25-token labels, and no worse on the
   reviewed sets) and nominees per chunk rise as chunks get fewer
   (`nominees_per_chunk`). Hitachi now returns five per system, including rail,
   lifting equipment and industrial machinery.
2. **The old similarity bands would mislabel every result.** The IC tabs call
   anything under 0.355 "Unlikely". A paragraph against a short code title
   scores about 0.25-0.45, so nearly everything would read "Unlikely". This tab
   shows similarity relative to the system's best and says why; it does not use
   those words.
3. **History chunks vote for junk.** Apple's founding paragraph points at
   cocoa/chocolate (the word "Apple"); "Mobile" pulled T-Mobile to Mobile Home
   Sites. The Segments step is where a person removes this; the model cannot.

**How good is the automatic set?** (live endpoint, 37 reviewed companies, set =
2-5 recommended, pool = recommended + 7 alternatives, the stepper's menu)

| System | set: any plausible code | set precision | set recall | pool: any plausible | pool recall |
|---|---|---|---|---|---|
| US SIC | 0.62 | 0.21 | 0.31 | 0.76 | 0.46 |
| ISIC Rev.4 | 0.81 | 0.23 | 0.46 | 0.89 | 0.59 |
| NACE Rev.2 | 0.73 | 0.23 | 0.42 | 0.86 | 0.59 |

The unaided set is right about a fifth of the time per code and contains a
plausible code in 62-81% of cases; the pool reaches one in 76-89% of cases. So
the stepper is not decoration: choosing from the pool is what turns a noisy
automatic set into a usable one, and for roughly one US company in four even
the pool has no plausible code. Do not describe the automatic output as an
answer.

**Next**
1. Use it: try more companies, including conglomerates (Apple, P&G, Hitachi,
   Tesla) and a unitary one (T-Mobile), and say what the stepper still lacks.
   Only then decide how many more companies to label.
2. Not built yet: the hierarchy roll-up step (choose a sector, then codes), the
   company's filed SIC shown beside our set, a live token meter on the
   description box, and per-system chunk handling (US benefits from chunking;
   ISIC and NACE do not).
3. Model bake-off (section 7) remains deferred.

---

## 11. Pivot design: narrow in US SIC, then map to the other systems (2026-10-04)

**Proposal (from the user).** The four-step stepper is too much for a business
user. Instead: help the user narrow to a small set of codes in **one** system
(US SIC) first. Then let them choose which target systems they care about
(Japan, EU NACE, ISIC), and use the selected US codes to find the matching
codes in those systems, by semantic search, keyword search or a combination.
The systems are used to search each other, which is tractable and also points
at a future crosswalk capability.

**Why it is attractive.** One judgement in one system instead of four pickers;
every target code carries its provenance ("mapped from US 3571"), which is a
crosswalk the user can read; the target-system step costs the user one click per
system; and the same mapper later serves code-to-code lookups with no company
text at all.

### 11.1 Experiments (`experiments/company-sic-eval/crosswalk_eval.py`)

All use the stored MiniLM vectors for the corpora, plus titles re-embedded on
their own. Reviewed sets, 37 companies, "any plausible" = at least one reviewer-
accepted code in the returned five.

**E1: does code-to-code matching work at all?** A label-free structural check:
335 ISIC Rev.4 classes have a four-digit code identical to a NACE Rev.2 class
(ISIC 4791 = NACE 47.91). Does the matcher put the identical class near the top?

| Matcher | ISIC to NACE top-1 / 3 / 5 | NACE to ISIC top-1 / 3 / 5 |
|---|---|---|
| semantic, stored breadcrumb vectors | 0.80 / 0.87 / 0.90 | 0.84 / 0.91 / 0.94 |
| semantic, titles only | 0.81 / 0.87 / 0.88 | 0.83 / 0.87 / 0.90 |
| keyword overlap | 0.79 / 0.84 / 0.87 | 0.81 / 0.85 / 0.88 |
| breadcrumb + title + keyword (rank fusion) | 0.80 / 0.86 / 0.89 | 0.83 / 0.90 / 0.92 |

Between systems whose wording is close, matching finds the counterpart about
four times in five at rank 1 and nine times in ten within five. The matchers are
nearly interchangeable. Misses are partly real (NACE splits some ISIC classes,
so "the identical code" is not the only right answer), so this is a floor.

**E2: the use case, with a perfect US narrowing (an upper bound).** Take the US
codes the reviewer accepted for each company, map them, compare with the
reviewed ISIC/NACE sets.

| Target | direct: description to target | pivot, best matcher | any / precision / recall |
|---|---|---|---|
| ISIC Rev.4 | 0.81 / 0.23 / 0.46 | semantic titles | **0.92 / 0.32 / 0.63** |
| NACE Rev.2 | 0.73 / 0.23 / 0.42 | semantic titles or breadcrumb fusion | **0.89 / 0.34 / 0.61** |

If the US codes are right, the mapped sets are clearly better than matching the
description straight into the target system.

**E2b: a person picks from the stepper's 12-code US menu (simulated).** The
simulated person picks exactly the menu codes the reviewer accepted, and where
the menu has none, the automatic five are used. The menu contained an accepted
US code for 28 of 37 companies (76%).

| Target | direct | pivot, semantic titles | pivot, combined query | pivot (3) + direct fill |
|---|---|---|---|---|
| ISIC, all 37 | 0.81 / 0.23 / 0.46 | 0.68 / 0.23 / 0.41 | 0.70 / 0.21 / 0.43 | 0.78 / 0.23 / 0.47 |
| ISIC, the 28 with a right menu code | 0.86 / 0.25 / 0.50 | 0.82 / 0.28 / 0.51 | 0.86 / 0.26 / 0.53 | 0.86 / 0.26 / 0.52 |
| NACE, all 37 | 0.73 / 0.23 / 0.42 | 0.65 / 0.23 / 0.38 | 0.78 / 0.24 / 0.46 | **0.84 / 0.27 / 0.51** |
| NACE, the 28 | 0.75 / 0.24 / 0.45 | 0.86 / 0.31 / 0.50 | **0.93 / 0.30 / 0.56** | 0.93 / 0.31 / 0.58 |

("Combined query" = the selected codes' titles joined into one query; "fill"
= three mapped codes plus direct matches up to five.)

With the automatic US set and no person involved, pivoting is **worse** than
direct (any-plausible 0.43-0.59 against 0.73-0.81): US errors carry into every
system. The pivot only pays off when the US step is good.

**Japan SIC** has no reviewed sets, so only a spot check: US 3571 Electronic
Computers maps to Japan 2841 Electronic circuit board, 7032 Electronic computers
and related equipment; US 7372 Prepackaged Software to 3913 Package software
services; US 5812 Eating Places to 7611 Eating places. Plausible, unmeasured.

### 11.1b Against the official crosswalks (research only; REMOVED from the product 2026-10-04)

> **Decision (user, 2026-10-04): the product does not use crosswalk tables.** Their
> licensing is unresolved (11.6), so the server, UI and data directory no longer
> contain or read them and the downloaded files were deleted. What follows is the
> measured evidence gathered before that decision, kept because it shows what
> similarity-only mapping gives up. Section 11.6 describes what was built instead.

The UN Statistics Division tables (ISIC Rev.4 <-> NACE Rev.2; ISIC Rev.3.1 ->
Rev.4; ISIC Rev.3 <-> US SIC 1987) are in `experiments/company-sic-eval/
crosswalks/` (`official_crosswalks.py` loads them; the JSIC Rev.13 <-> ISIC Rev.4
workbook is downloaded but is legacy Excel with no reader installed yet). The
chain US SIC -> ISIC Rev.3 (taken as 3.1) -> ISIC Rev.4 -> NACE Rev.2 covers 989
of our 1,005 US classes. Official mappings are many-to-many: a US class lists
5.2 ISIC counterparts on average, 8.6 NACE.

**E3: the similarity mapper against the official tables** ("any official
counterpart in the top k"; stored breadcrumb vectors, the best matcher):

| Mapping | top-1 | top-3 | top-5 | top-10 |
|---|---|---|---|---|
| US SIC to ISIC Rev.4 | 0.62 | 0.82 | 0.88 | 0.94 |
| US SIC to NACE Rev.2 | 0.68 | 0.83 | 0.88 | 0.95 |
| ISIC Rev.4 to NACE Rev.2 | 0.99 | 1.00 | 1.00 | 1.00 |
| NACE Rev.2 to ISIC Rev.4 | 0.93 | 0.97 | 0.99 | 1.00 |

The hierarchy text matters: breadcrumb vectors beat titles alone (0.88 vs 0.81
top-5 for US to ISIC), and keyword overlap is weak across systems (0.57). Closely
related systems map almost perfectly; US SIC, being older and differently
structured, maps usefully but not exactly.

**E4: official tables versus the similarity mapper, on the reviewed companies**
(any plausible / precision / recall / mean set size, ISIC target; NACE is the
same shape):

| US codes given | direct (no US step) | official, unranked | official, re-ranked by the description (top 5) | similarity mapper |
|---|---|---|---|---|
| perfect set | 0.81 / 0.23 / 0.47 / 5 | 1.00 / 0.31 / 0.94 / 12.8 | **0.92 / 0.41 / 0.69 / 4.6** | 0.92 / 0.32 / 0.63 / 4.9 |
| person picks from the 12-code menu | same | 0.81 / 0.31 / 0.57 / 9.1 | **0.76 / 0.36 / 0.51 / 4.2** | 0.68 / 0.23 / 0.41 / 4.4 |
| automatic five | same | 0.73 / 0.11 / 0.46 / 15 | 0.59 / 0.18 / 0.36 / 4.8 | 0.51 / 0.13 / 0.27 / 5 |

**What changes.** (1) Use the **official crosswalk as the mapper** wherever one
exists; the similarity mapper is the fallback for unmapped codes and for pairs
with no table (and the way to check coverage). (2) The best five come from
**ranking the official candidates by how well they fit the description**: with a
perfect US set that is the most precise option (0.41) and keeps 0.92 any-plausible;
with a realistic person's picks it is on par with direct matching on coverage and
clearly better on precision (0.36 vs 0.23). (3) With no description (a pure
code-to-code lookup) return the official set unranked, ordered by similarity,
with its provenance. (4) ISIC Rev.4 is the natural hub: every other system links
to it, so any system can be the starting point (the user's refinement).

### 11.2 What this means

1. **The pivot is a UX win more than an accuracy win.** With a realistic US
   choice it roughly ties direct matching, and beats it on NACE; with a perfect
   US choice it beats it clearly. It does not lose accuracy, and it replaces four
   pickers with one.
2. **All the quality now rides on the US step.** Automatic US set: right 62% of
   the time; its 12-code menu: 76%. The US screen is where the design effort and
   the human should go, and it needs a "none of these fit" exit for the quarter
   of companies where nothing in the menu is right.
3. **Use direct matching as a safety net, not as the main path.** Mapping first
   and filling up to five from the description (pivot 3 + direct) was the best or
   tied-best option in every column that mattered.
4. **It is a crosswalk in embryo.** E1 shows label-based mapping is usable but
   not authoritative. Official tables exist (JSIC Rev.13 to ISIC Rev.4 from
   Japan's Statistics Bureau, ISIC Rev.4 to NACE Rev.2 from the UN and Eurostat,
   US SIC to ISIC Rev.3 from the UN, and ISIC Rev.3.1 to Rev.4 to chain). They
   would give true ground truth for the mapper, and could back an exact
   code-to-code lookup alongside the semantic one. Not downloaded; needs a
   decision (section 11.5).

### 11.3 Revised UX (superseded by the compact stepper in 11.6)

One page, two phases, no stepper chrome.

- **Phase 1, "Industry (US SIC)".** Description in (name lookup or paste, large
  box). On submit, show the recommended US SIC codes (2-5) as checked rows with
  their hierarchy, and a "More candidates" list. Each row has "why" (the
  supporting segment). A collapsible "How we read your text" holds the segment
  reading view with switches, so a user can drop a history paragraph and
  re-match without leaving the page. If nothing fits: "None of these fit"
  prompts for more text instead of forcing a pick. The user confirms or adjusts
  the set: that is the one real decision.
- **Phase 2, "Other systems".** Chips for Japan SIC, EU NACE, ISIC (US already
  done). Selecting one maps the confirmed US codes into it and shows 2-5 codes
  with hierarchy, each labelled with the US code(s) it came from, plus a one-
  line limitation note. Switching chips is free; it re-maps instantly.
- **Result** is simply the page: US set plus whichever systems are chosen; copy
  or View JSON covers all of it.

### 11.4 API and implementation consequences

- Keep `POST /V4.0/global/sic/match` for the US phase, restricted to US SIC by
  default (a `systems` field to opt others in). Returns the recommended set, the
  alternatives and the chunks as today.
- New `POST /V4.0/global/sic/map`: `{ "codes": ["3571","7372"], "from":
  "US SIC", "to": ["ISIC Rev. 4","EU NACE","Japan SIC"], "description": "..."
  (optional, for the direct fill) }`. For each target: 2-5 codes, each with
  hierarchy and `from_codes`. Method: the selected codes' titles joined as one
  query plus per-code nominations, then filled from the description when given
  (E2b's best combination). Code-to-code needs no company text, so this
  endpoint is also the future crosswalk lookup.
- Reuses what exists: embedder, per-system search, hierarchy, the chunker for
  the description fill. No new data; an official-crosswalk table, if approved,
  is a small additional file in the data directory.
- UI: Industry Match becomes a single page; the four-step rail and its Segments
  / Codes / Result sections are merged into Phase 1 and Phase 2.

### 11.5 Open decisions

1. Download the official crosswalk tables to use as ground truth (and possibly
   as an exact lookup)? Which ones?
2. Default for Phase 2: all target systems pre-selected, or none?
3. Confirm replacing the four-step stepper with the two-phase page.
4. How much to invest in the US step: it is the quality bottleneck. Options:
   better US-only tuning (US benefits from chunking, unlike ISIC/NACE, so it
   can use settings the others cannot) and a "none of these fit" exit.
5. Japan SIC: needs reviewed sets or an official crosswalk before any accuracy
   claim.

### 11.6 As built (2026-10-04, later), after the crosswalk tables were removed

Answers from the user: all other systems are selected by default; one page in two
phases; the user can choose the starting system (US SIC by default); and, last,
**no crosswalk tables**: they were downloaded, used in the experiments above, then
removed from the server, UI, data directory and disk (see the licensing note below).

- `crates/sic/src/map.rs` maps a chosen set into other systems **by similarity
  only**. Each chosen code nominates its 5 most similar entries in the target system
  (using the stored hierarchy-text vectors, which beat title-only vectors). Without a
  description they are ranked by similarity to the chosen codes. With one, the top 3
  mapped codes (ranked by the mean of similarity to the chosen codes and fit to the
  description) are kept and the set is **filled to five by matching the description
  straight into the target system**. Each entry says whether it came from the chosen
  codes (`basis: codes`, with `from_codes`) or from the description.
- **Measured without any tables** (`mapper_variants.py`, 37 reviewed companies, a
  person simulated as picking the accepted codes from the stepper's 12-code menu,
  falling back to the automatic five): the chosen variant reaches a plausible code
  86% of the time for ISIC and 84% for NACE (direct matching: 81% and 76%). When the
  menu had a right US code (28 of 37) every variant is above 90%, and 8 nominees per
  code ranked by fit reached 96% with precision 0.31-0.33. The official tables did
  better (92% with precision 0.41 for a perfect US set), which is the cost of the
  decision, but similarity-only is already at or above direct matching.
- `POST /V4.0/global/sic/map` `{from, codes, to?, description?}`; about 180-220 ms
  with a description. Doubles as a code-to-code lookup when no description is given.
- `POST /V4.0/global/sic/match` takes `systems` and defaults to US SIC only.
- **The Industry Match tab is a compact stepper** (the user found the two-phase page
  still too much and set the shape): **1 Describe** (name lookup or pasted text, always
  editable, plus the system to start in); **2 Codes** (segments and key phrases on the
  left with switches and Re-match, the starting system's codes on the right to keep 2-5,
  and the chips for which systems to find next, all on by default, so it fits one screen);
  **one step per chosen target system** (its codes, found by similarity, each with
  "from <source codes>" or "from description"); and **Report** (every chosen code per
  system with its hierarchy; copy as text, View JSON). The step rail is dynamic and any
  reachable step can be revisited. Code rows are one line (checkbox, code, title,
  similarity bar) with the hierarchy and the reason behind a small arrow. The map is
  computed when leaving step 2 and recomputed only if the codes or systems changed.
  The stepper is a **fixed-height panel**: the rail on top, the Back/Next buttons pinned at the
  bottom, and only the lists (segments and codes scroll independently) in between. Buttons are orange
  outline on black, solid orange with black text on hover. Next is blocked only for 0 codes or more
  than 5 (the minimum was relaxed from 2 to 1 so a single-business company is not forced to add a
  filler code), and the reason is shown beside the button, not only in a heading that can scroll away.
  **Report PDF:** the Report step has a Download PDF button. It builds a real PDF in the browser
  (`static/js/simple-pdf.js`, no dependencies, A4, Helvetica, selectable text, automatic page breaks and
  "Page x of y" footers) with the company name, the description as entered, the starting system and how
  many segments and phrases were matched, then every chosen code per system with its full hierarchy and
  where it came from, ending with the not-an-official-classification note. Limits: text in the PDF is
  Latin-1 plus common punctuation, so characters outside it (IPA, Japanese script) print as "?"; the
  company name comes from the lookup or the name box, else "Company (name not given)".

**Why the crosswalk tables were removed: licensing (checked 2026-10-04; not legal advice).** Sources:
UN Statistics Division files `ISIC4_NACE2.txt`, `ISIC31_ISIC4.txt` and
`ISIC-USSIC.csv` (the last is the 1993 "International Concordance between the
Industrial Classifications" input table), and Japan's `jsic13_isic4.xls`
(soumu.go.jp, Ministry of Internal Affairs and Communications). **None of the
files states a licence.** The UN's general copyright page says materials on its
site may not be used, reproduced or transmitted without written permission, with
no dataset or non-commercial allowance, and ISIC texts are marked "Copyright (c)
United Nations". The Japanese page's footer reads "All Rights Reserved"; the
Statistics Bureau's own site publishes under the Government of Japan Standard
Terms of Use v2.0 (compatible with CC BY 4.0), but I could not confirm that those
terms cover this soumu.go.jp file. So: fine for local development, **not cleared
for redistribution**, and the mapped results the API serves are derived from them.
Release gate: obtain written permission from UN Publications (Rights and
Permissions) and read the soumu.go.jp "Website Information" page, or replace the
tables with ones whose terms are clear (candidates to verify: Eurostat's
NACE Rev.2 / ISIC Rev.4 correspondence from its RAMON/Metadata server, and the
US Census Bureau's NAICS-SIC and NAICS-ISIC concordances, which are US government
works).

**Still open.** The similarity mapper is weaker than the official tables for Japan
SIC in particular (measured before removal: ISIC to Japan top-5 0.71, against 0.88 for
US to ISIC); Japan matches are unverified suggestions and the page says so. Official
tables could return later only with clear terms (candidates to verify: Eurostat's NACE
Rev.2 / ISIC Rev.4 correspondence, and the US Census Bureau's NAICS-SIC and NAICS-ISIC
concordances, which are US government works). The sector roll-up and the filed-SIC
comparison remain unbuilt; a live scorer for `/map` against the reviewed sets is not
written.

---

## 12. Marketing-style descriptions: the Hitachi case (2026-10-04)

**The report.** A hand-written Hitachi description covering every sector came back
"crap": US SIC returned Hardwood Veneer, Carbon Black and Computer Facilities
Management; ISIC returned Repair of consumer electronics and Manufacture of veneer
sheets. The text is 140 word pieces, four segments.

**Diagnosis.** (1) Three of the four segments are not about the business at all
(headquarters, founding, headcount, a carbon-neutrality target) and each still
nominated its top codes, so they cast junk votes ("carbon neutrality" pulled Carbon
and Graphite Products). (2) The one real segment lists the businesses ("data
storage", "power grids and clean energy solutions", "advanced railway mobility",
"industrial systems") but was matched as a single vector, which dilutes every item.
A short phrase matches a short code title far better than the paragraph around it.

**Experiments** (`selection_variants.py`, reviewed sets, set of 2-5): a relevance
gate on whole segments helped US precision slightly but cost ISIC and NACE a lot
(any-plausible 0.81 down to 0.59-0.68), so it is not used. **Querying the key
phrases on their own** raised US from 0.62 to 0.70 and NACE from 0.73 to 0.78 and
left ISIC about even (0.81 to 0.78). Weighting each vote by its similarity (so a
weak nomination cannot outvote a strong one by repetition) held those numbers and
demoted junk. A similarity floor on segment votes hurt ISIC and NACE and was dropped.

**Built.** `phrases()` (mirrored in `chunker.py` as the spec; identical output on all
200 descriptions): split on commas, semicolons, brackets, "and", "including", "such as",
"via", "with", "through", "across"; drop filler lead-ins ("specializing in"); keep
fragments of 2-7 words with at least two content words; drop founding, headquarters,
headcount and similar. Each phrase nominates its single best code if the similarity is at
least 0.40. Recommended codes rank by summed similarity of their nominations. The match
response carries `input.phrases`, and an entry says whether a segment or a phrase was
its best evidence. The Segments panel lists the phrases. Live scores on the 37 reviewed
companies: US SIC any-plausible 0.70, ISIC 0.78, NACE 0.78 (set precision 0.21-0.24).

**What Hitachi returns now.** ISIC: Electric power generation, transmission and
distribution (from "power grids"), Passenger rail transport (from "advanced railway
mobility"), Installation of industrial machinery (from "industrial systems"), Lifting and
handling equipment, plus one junk code (Repair of consumer electronics). US SIC:
Electric and Other Services Combined, Railroads, plus three weak ones (Industrial
Patterns, Direct Mail Advertising, Computer Terminals). Better, not good: the US set
still depends on the person choosing, and "data storage" no longer reaches the top
five for US SIC. A person keeps the good ones and drops the rest; the automatic set
is a starting point, not an answer.

**Stop words: tested, no effect (2026-10-04, `stopword_eval.py`).** Question: does stripping
filler words from the text we embed help? Rust has the `stop-words` crate (Stopwords-ISO
English, about 1,300 words, and the NLTK list behind its `nltk` feature). Compared with the
current pipeline (no stripping), on the 37 reviewed companies and on the 200 filer-SIC
companies: NLTK (179 words), scikit-learn (318) and a list learned from our own data (79
words frequent in the descriptions and absent from every code label), each applied to the
segments, to the phrases, or to both.

| Variant | US any / prec / recall | ISIC | NACE | filer US group@5 / class@10 |
|---|---|---|---|---|
| none (current) | 0.70 / 0.22 / 0.33 | 0.78 / 0.22 / 0.44 | 0.78 / 0.24 / 0.45 | 0.42 / 0.56 |
| NLTK, segments only | 0.65 / 0.20 / 0.29 | 0.76 / 0.20 / 0.41 | 0.78 / 0.22 / 0.41 | 0.42 / 0.57 |
| NLTK, phrases only | 0.70 / 0.21 / 0.32 | 0.78 / 0.22 / 0.44 | 0.81 / 0.25 / 0.47 | 0.42 / 0.56 |
| NLTK, both | 0.65 / 0.19 / 0.28 | 0.76 / 0.20 / 0.41 | 0.76 / 0.22 / 0.41 | 0.42 / 0.57 |
| scikit-learn 318, both | 0.65 / 0.19 / 0.28 | 0.78 / 0.22 / 0.45 | 0.78 / 0.24 / 0.46 | 0.45 / 0.59 |
| learned list, both | 0.70 / 0.23 / 0.35 | 0.76 / 0.22 / 0.45 | 0.76 / 0.23 / 0.44 | 0.41 / 0.58 |
| NLTK + learned, both | 0.70 / 0.22 / 0.33 | 0.76 / 0.22 / 0.46 | 0.78 / 0.23 / 0.45 | 0.44 / 0.60 |

Every difference is within the noise of these sample sizes (about 0.05 on 37 companies and
0.03-0.04 on 200); stripping from the segments alone slightly hurts US on the reviewed
sets, and nothing is consistently better. MiniLM was trained on natural sentences and its
tokenizer already handles function words, so removing them gains nothing measurable.
**Decision: no stop-word dependency and no stripping of embedded text.** Not tested: the
full Stopwords-ISO list (not local; it is the most aggressive and unlikely to help), and
using a stop-word list inside the phrase *extractor* to decide what counts as a content
word, which is a separate question from what is embedded.

**Phrase extraction: variants tested (2026-10-04, `phrase_variants.py`).** Prompted by junk in the
phrase list on long pages (P&G: "which includes Head Shoulders", "James Gamble", "th on the Forbes
Global", "The Procter Gamble Company"). Extractors tried, each scored like the rest (reviewed sets
and the 200 filer companies, here "is the filer's group / exact class inside the recommended five"):

| Extractor | phrases per company | US any / prec / recall | ISIC any | NACE any | filer group / class in set |
|---|---|---|---|---|---|
| no phrases | 0 | 0.65 / 0.21 / 0.31 | 0.81 | 0.73 | 0.42 / 0.40 |
| current (E0) | 25 | 0.70 / 0.22 / 0.33 | 0.78 | 0.78 | 0.41 / 0.40 |
| E0 + the two bug fixes (E0fix) | 27 | 0.70 / 0.22 / 0.33 | 0.78 | 0.78 | 0.41 / 0.40 |
| E3: drop digits, `&`, names; NLTK trims | 15 | 0.65 / 0.21 / 0.31 | 0.78 | 0.81 | 0.43 / 0.42 |
| E5: permissive (1-word phrases allowed) | 40 | 0.76 / 0.25 / 0.37 | 0.78 | 0.78 | 0.43 / 0.42 |

- **Nothing here is distinguishable from noise.** On the 200 filer companies phrases add nothing
  (0.42 without, 0.41 with); on the 37 reviewed they give US +0.05 to +0.11 and NACE +0.05 and
  cost ISIC 0.03. E5's 0.76 for US is the best number and is not trusted at N=37.
- **The strict extractors threw away useful content.** Dropping fragments with `&` or mostly
  capitalised words removed P&G's division names ("Fabric & Home Care", "Health Care"), which are
  the real categories there; E3 left P&G with two junk phrases.
- **Context frames hurt.** Wrapping each phrase ("X industry", "manufacture of X", "X products",
  "business of X") lowered every score (US 0.76 down to 0.62-0.73, ISIC to 0.65-0.73). The frames
  do steer toward product labels (power grids to Steam and Gas Turbines, railway mobility to
  Railroad Equipment, data storage to Computer Storage Devices), which is right for a manufacturer
  and wrong for everyone else, so a frame would need to know the kind of company. Not adopted.
- **The interesting matches are literal wording matches, and they show the wording gap.** "Beauty"
  finds Beauty Shops, "Grooming" Barber Shops, "Health Care" Home Health Care Services,
  "Family Care" Residential Care: the codes describe services, P&G makes products. Brand names
  (Pantene, Tide) match nothing sensible, as expected.
- **Adopted: only the two bug fixes** (`&` means "and"; a token containing a digit is a break
  point). Scores are identical to before and the broken fragments are gone ("Home Care" and
  "Family Care" now appear, "th on the Forbes Global" does not). Mirrored in `chunker.py` and the
  Rust `phrases()`, with tests; the two agree on all 200 descriptions. The wider extractors
  (E3, E5) are left as research.

**Named-entity removal: tested with a generous proxy, no help (2026-10-04, `ner_proxy_eval.py`).**
The idea: an NER pass could remove people, brands, places and subsidiaries ("James Gamble",
"Pantene", "Hitachi Vantara") that produce junk matches. No NER model is installed, so the upper
bound was simulated by masking every capitalised word that does not start a sentence, which
catches at least as many names as a real NER would (plus false positives such as Title Case
headings). Results (reviewed 37 / filer 200):

| Variant | US any | ISIC any | NACE any | filer group@5 / class@10 |
|---|---|---|---|---|
| none (current) | 0.70 | 0.78 | 0.78 | 0.42 / 0.56 |
| mask names in segments | 0.68 | 0.70 | 0.73 | 0.40 / 0.58 |
| mask names in phrases | 0.70 | 0.78 | 0.81 | 0.42 / 0.56 |
| mask in segments and phrases | 0.68 | 0.70 | 0.76 | 0.40 / 0.58 |
| extract phrases from the masked text | 0.68 | 0.78 | 0.81 | 0.42 / 0.56 |

Masking names in the segments hurts ISIC (0.78 to 0.70); in the phrases it is neutral. Reasons it
cannot help much: names carry some industry signal for the embedding ("Vantara", "Gillette"); the
junk phrases that survive are mostly ordinary words that match a code literally, not entities; and
an NER tag says a word is a PRODUCT or ORG, not what industry it belongs to. **Not pursued**: it
would add a model download and a new dependency for no measurable gain. If any NLP step is worth
trying here it is noun-phrase chunking (picking out what the company makes or does), which is a
different tool from NER.

**Limits to expect.** Marketing prose names businesses in abstract terms ("digital
solutions", "social innovation") that match nothing well; a description that states what
the company makes or sells will always do better. Showing the phrases next to the
results lets the user see what was looked for and edit the text.

---

## Sources

- [all-MiniLM-L6-v2 model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2): 256 word-piece truncation, 128-token training length.
- [Late Chunking, arXiv 2409.04701](https://arxiv.org/html/2409.04701v3) and [Jina's explanation](https://jina.ai/news/late-chunking-in-long-context-embedding-models/).
- [ONS ClassifAI](https://datasciencecampus.ons.gov.uk/classifai-exploring-the-use-of-large-language-models-llms-to-assign-free-text-to-commonly-used-classifications): retrieve with MiniLM, select with an LLM, "uncodable" state.
- Census BEACON: [working paper](https://www.census.gov/library/working-papers/2024/econ/industry-self-classification-in-the-economic-census.html), [FCSM 2023 slides](https://www.fcsm.gov/assets/files/docs/2023-conference-docs/A5.1_Whitehead.pdf).
- [RAG-based industry classification (summary)](https://www.zenml.io/llmops-database/rag-based-industry-classification-system-for-customer-segmentation).
- [How the SEC treats SIC codes](https://www.thecorporatecounsel.net/blog/2016/03/sic-codes-how-does-the-sec-assign-them.html).
- [Multi-step form guidance](https://uxplanet.org/how-to-design-a-magical-form-wizard-e0c6458f6318).
- Query-document size imbalance in neural retrieval: surfaced through search
  results only (no single paper read in full); treat as background, not as a
  cited result.
- Local measurements: description lengths and the chunking pilot (this
  session's scratch scripts, to be moved into `experiments/` when work
  starts); `fastembed` 7.1.0 model catalogue from the local cargo registry.
