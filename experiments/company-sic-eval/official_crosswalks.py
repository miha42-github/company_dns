"""Loaders for the official correspondence tables in crosswalks/ (UN Statistics
Division). See crosswalks/README.md for sources. All return dict[str, set[str]].

  isic4_nace2()   ISIC Rev.4 class (4 digits)  -> NACE Rev.2 classes ("NN.NN")   [+ reverse]
  isic31_isic4()  ISIC Rev.3.1 class           -> ISIC Rev.4 classes
  ussic_isic3()   US SIC 1987 class (4 digits) -> ISIC Rev.3 classes
  us_to_isic4()   chain US SIC -> ISIC Rev.3 (treated as 3.1) -> ISIC Rev.4
  us_to_nace2()   chain through ISIC Rev.4 -> NACE Rev.2
  jsic13_isic4()  JSIC Rev.13 -> ISIC Rev.4 (+ reverse), from jsic13_isic4.csv
  us_to_jsic13()  chain US SIC -> ISIC Rev.4 -> JSIC Rev.13

ISIC Rev.3 and Rev.3.1 differ in a few classes; the chain treats an ISIC 3 code
as the same code in 3.1, and a US code is simply uncovered when the chain breaks.
"""
import csv
from collections import defaultdict
from pathlib import Path

D = Path(__file__).parent / "crosswalks"


def _rows(name):
    with open(D / name, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def isic4_nace2():
    fwd, rev = defaultdict(set), defaultdict(set)
    for r in _rows("ISIC4_NACE2.txt"):
        i, n = r["ISIC4code"], r["NACE2code"]
        if len(i) == 4 and i.isdigit() and len(n) == 5 and n[2] == ".":
            fwd[i].add(n)
            rev[n].add(i)
    return dict(fwd), dict(rev)


def isic31_isic4():
    out = defaultdict(set)
    for r in _rows("ISIC31_ISIC4.txt"):
        a, b = r["ISIC31code"], r["ISIC4code"]
        if len(a) == 4 and len(b) == 4:
            out[a].add(b)
    return dict(out)


def ussic_isic3():
    out = defaultdict(set)
    for r in _rows("ISIC-USSIC.csv"):
        i, u = r["ISIC3"], r["US-SIC"]
        if len(i) == 4 and len(u) == 4 and u.isdigit():
            out[u].add(i)
    return dict(out)


def us_to_isic4():
    a, b = ussic_isic3(), isic31_isic4()
    out = {}
    for u, i3s in a.items():
        g = set().union(*(b.get(i, set()) for i in i3s)) if i3s else set()
        if g:
            out[u] = g
    return out


def us_to_nace2():
    f, _ = isic4_nace2()
    out = {}
    for u, i4s in us_to_isic4().items():
        g = set().union(*(f.get(i, set()) for i in i4s))
        if g:
            out[u] = g
    return out


def jsic13_isic4():
    fwd, rev = defaultdict(set), defaultdict(set)
    for r in _rows("jsic13_isic4.csv"):
        fwd[r["JSIC13"]].add(r["ISIC4"])
        rev[r["ISIC4"]].add(r["JSIC13"])
    return dict(fwd), dict(rev)


def us_to_jsic13():
    _, rev = jsic13_isic4()
    out = {}
    for u, i4s in us_to_isic4().items():
        g = set().union(*(rev.get(i, set()) for i in i4s))
        if g:
            out[u] = g
    return out
