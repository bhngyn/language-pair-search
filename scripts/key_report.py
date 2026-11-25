"""Precision cost of a match_key change, measured over a built dictionary.db.

    python scripts/key_report.py path/to/dictionary.db [--examples 20]

Recomputes translit.match_key for every name with the installed code and compares it with the `names.key` stored
in the file (the keys of the KEY_VERSION it was built with). Read-only. Reports, before (stored) and after (current):

- fold pairs: pairs of different entries that share a key although no identical (normalised) name links them under
  that key. A village name shared by 40 villages is not a fold pair; Hamid ~ Hamed for two different places is.
  This is the collision count that key folding adds, the precision cost.
- Latin <-> Cyrillic agreement: of the entries that have both a Latin and a Cyrillic name, the share where some
  Latin name and some Cyrillic name have the same key (what lets a Latin query reach the Cyrillic spelling).
- new merges: example keys that gained a fold pair, for eyeballing.
"""

import argparse
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from language_pair_search import textnorm, translit  # noqa: E402


def fold_pairs(rows, script=None):
    """{key: set of (e1, e2)} for entry pairs sharing a key with no common normalised name under it."""
    by_key = defaultdict(lambda: defaultdict(set))           # key -> normalised name -> entries
    for eid, name, key, sc in rows:
        if key and (script is None or sc == script):
            by_key[key][textnorm.normalize(name).strip()].add(eid)
    out = {}
    for key, names in by_key.items():
        ents = sorted(set().union(*names.values()))
        if len(ents) < 2 or len(names) < 2:
            continue
        linked = defaultdict(set)
        for es in names.values():
            for e in es:
                linked[e] |= es
        pairs = {(a, b) for i, a in enumerate(ents) for b in ents[i + 1:] if b not in linked[a]}
        if pairs:
            out[key] = pairs
    return out


def agreement(rows):
    keys = defaultdict(lambda: {"la": set(), "cy": set()})
    for eid, _name, key, sc in rows:
        if key and sc in ("la", "cy"):
            keys[eid][sc].add(key)
    both = [k for k in keys.values() if k["la"] and k["cy"]]
    return sum(1 for k in both if k["la"] & k["cy"]) / max(1, len(both)), len(both)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--examples", type=int, default=20)
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    kv = dict(con.execute("SELECT key, value FROM meta")).get("key_version", "?")
    raw = con.execute("SELECT entry_id, name, key FROM names").fetchall()
    old = [(e, n, k, translit.script_of(n)) for e, n, k in raw]
    new = [(e, n, translit.match_key(n), sc) for e, n, _k, sc in old]
    changed = defaultdict(int)
    for (_, _, k0, sc), (_, _, k1, _) in zip(old, new):
        if k0 != k1:
            changed[sc or "other"] += 1
    print(f"{a.db}: {len(raw)} names, stored KEY_VERSION {kv}, current {translit.KEY_VERSION}")
    print("keys changed by script:", dict(changed) or "none")
    for label, sc in (("Latin", "la"), ("Cyrillic", "cy"), ("all", None)):
        f0, f1 = fold_pairs(old, sc), fold_pairs(new, sc)
        n0, n1 = sum(map(len, f0.values())), sum(map(len, f1.values()))
        print(f"fold pairs ({label}): {n0} -> {n1} ({n1 - n0:+d}, {100 * (n1 - n0) / max(1, n0):+.2f}%)")
        if sc == "la":
            lat0, lat1 = f0, f1
    ag0, nb = agreement(old)
    ag1, _ = agreement(new)
    print(f"Latin <-> Cyrillic agreement: {100 * ag0:.2f}% -> {100 * ag1:.2f}% of {nb} entries with both")
    if a.examples:
        names = defaultdict(set)
        for _e, n, k, sc in new:
            if sc == "la":
                names[k].add(n)
        gain = {k: len(v) - len(lat0.get(k, ())) for k, v in lat1.items()}
        gained = sorted((k for k in gain if gain[k] > 0), key=lambda k: -gain[k])
        print(f"keys that gained Latin fold pairs: {len(gained)}; largest:")
        for k in gained[:a.examples]:
            print(f"  {k!r}: +{gain[k]} pairs  e.g. {sorted(names[k])[:6]}")


if __name__ == "__main__":
    main()
