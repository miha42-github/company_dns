"""Sentence-window chunker for long company descriptions (plan sec. 4, strategy C).

Pure Python so the Rust port can be tested against the same cases. Packs whole
sentences up to `target` tokens, with a one-sentence overlap carried into the
next chunk only when that sentence is under half the target. A single sentence
longer than `hard_cap` is split on commas/semicolons, then by words.
"""
import re

# Abbreviations whose trailing period does not end a sentence.
ABBREV = {"inc", "corp", "co", "ltd", "llc", "plc", "u.s", "u.k", "st", "no", "mr", "mrs", "ms", "dr",
          "jr", "sr", "vs", "etc", "e.g", "i.e", "approx", "dept", "est", "bros", "intl", "mt", "ft"}
_BOUNDARY = re.compile(r'([.!?]["\')\]]*)\s+(?=["\'(\[]?[A-Z0-9])')


def split_sentences(text):
    text = re.sub(r"\s+", " ", text).strip()
    out, start = [], 0
    for m in _BOUNDARY.finditer(text):
        piece = text[start:m.end(1)]
        last = re.split(r"\s+", piece.rstrip(".!?\"')]"))[-1].lower().strip("(")
        # keep going when the "sentence" ends in an abbreviation or a single initial ("J. Smith")
        if m.group(1).startswith(".") and (last in ABBREV or re.fullmatch(r"[a-z]", last or "")):
            continue
        out.append(piece.strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def _split_long(sentence, count, hard_cap):
    """Break an over-long sentence at clause marks, then at word boundaries."""
    if count(sentence) <= hard_cap:
        return [sentence]
    parts = [p.strip() for p in re.split(r"(?<=[;,])\s+", sentence) if p.strip()]
    out, cur = [], ""
    for p in parts:
        cand = f"{cur} {p}".strip()
        if cur and count(cand) > hard_cap:
            out.append(cur)
            cur = p
        else:
            cur = cand
    if cur:
        out.append(cur)
    final = []
    for p in out:
        if count(p) <= hard_cap:
            final.append(p)
            continue
        words, cur = p.split(), ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if cur and count(cand) > hard_cap:
                final.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            final.append(cur)
    return final


def chunk(text, count, target=128, hard_cap=200):
    """Return a list of chunk strings. `count(str) -> int` is the tokenizer's token count."""
    sentences = []
    for s in split_sentences(text):
        sentences.extend(_split_long(s, count, hard_cap))
    chunks, cur, n = [], [], 0
    for s in sentences:
        k = count(s)
        if cur and n + k > target:
            chunks.append(" ".join(cur))
            keep = cur[-1] if count(cur[-1]) < target // 2 else None
            cur, n = ([keep], count(keep)) if keep else ([], 0)
        cur.append(s)
        n += k
    if cur:
        chunks.append(" ".join(cur))
    return chunks


# ---------------------------------------------------------------- key phrases
# Marketing-style descriptions list their businesses ("data storage", "power grids
# and clean energy solutions", "advanced railway mobility"). A short phrase matches
# a short code title far better than the paragraph it sits in, so each phrase is
# also queried on its own (docs/plans/company-sic-match.md sec. 12).
_SPLIT = re.compile(r"\s*(?:[;,:()—]|\band\b|\bincluding\b|\bsuch as\b|\bvia\b|\bwith\b|\bthrough\b|\bacross\b)\s*", re.I)
_FILLER = re.compile(r"^(specializing in|focused on|focus on|such as|including|operates across|operates in|offers|provides|provide|delivers|develops|manufactures|makes|sells|engaged in|active in|known for)\s+", re.I)
_STOP = set("the a an of in on to for by as is are was were has have its their our company companies group global major leading several key world worldwide".split())
_NONBIZ = set("founded headquartered headquarters employees workforce committed achieving neutrality evolved nearly globally innovation transformation operates".split())


def phrases(text):
    """Short business phrases from `text`: fragments of 2-7 words with at least two content words."""
    # "&" means "and" (so "Fabric & Home Care" splits cleanly), and a token containing a digit
    # ("60th", "2030", "290,000") is a break point, not text to be stripped of its digits
    text = re.sub(r"\s*&\s*", " and ", text)
    text = re.sub(r"\b\S*\d\S*\b", ",", text)
    out, seen = [], set()
    for s in split_sentences(re.sub(r"\s+", " ", text).strip()):
        for frag in _SPLIT.split(s):
            frag = _FILLER.sub("", frag.strip())
            w = re.findall(r"[A-Za-z][A-Za-z\-]+", frag)
            if any(x.lower() in _NONBIZ for x in w):
                continue
            content = [x for x in w if x.lower() not in _STOP]
            if 2 <= len(w) <= 7 and len(content) >= 2:
                f = " ".join(w).lower()
                if f not in seen:
                    seen.add(f)
                    out.append(" ".join(w))
    return out
