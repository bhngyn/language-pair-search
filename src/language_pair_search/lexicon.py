"""
Multilingual search expansion and place-name lookup over a read-only dictionary.

The dictionary (data/gazetteer/dictionary.db, built once by gazetteer_build.py, read-only at runtime,
never fetched) links names of the same place or term across scripts and spellings. A search for
`Bakhmut` becomes `("bakhmut"* OR "бахмут"* OR "артемовск"* ...)`. Caller edits (extra names, hidden
names, extra entries) are passed in as an `Edits` object, never written to the dictionary file.

expand() returns the "expansion" object that search, comments search, CSV export and alert rules
share: the exact FTS5 expression that ran, the groups behind it (each with removable alternatives)
and a dict_version, so a recorded search can be re-run the same way later. If dictionary.db is
missing, only the Cyrillic-romanisation groups are produced.

The dictionary is not bundled: build it with `python -m language_pair_search.gazetteer_build`, then point the
library at it with set_dictionary(path) or the environment variable LANGUAGE_PAIR_DICT.
"""

import hashlib
import itertools
import json
import os
import re
import sqlite3
import threading
import unicodedata

from . import textnorm, translit

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
ENV_DICT = "LANGUAGE_PAIR_DICT"
_dict_path = None       # set by set_dictionary()

MAX_SPAN = 5            # longest run of query words looked up as one name
MAX_ENTRIES = 5         # entries per group whose names become alternatives (rest counted in more_entries)
MAX_ALTS_GROUP = 16
MAX_ALTS_TOTAL = 120    # keeps the FTS expression a sane size
MAX_NEAR = 24           # NEAR() combinations an expanded `a NEAR b` may become
LANGS = ("en", "ar", "ru", "uk", "latn", "other")
_LANG_ORDER = {l: i for i, l in enumerate(LANGS)}
_INFLECT = "аяоеьйыиую"  # Cyrillic final letters dropped so Одесса also finds Одессе
_ARTICLES = sorted(translit._LAT_ARTICLE, key=len, reverse=True)     # joined Latin articles: alfashir, elgeneina

# Common English words that must not trigger a place lookup on their own ("Will", "Mark", "Hill"...).
STOPWORDS = frozenset("""
about above after again against almost along already also although always another around away back been before
being below between both bring but came can come could dont down during each either else enough even ever every
find first from gave get give goes going gone good great have having here high himself into just keep kept know
last least left less like little long look made make many maybe might more most much must near need never next
none once only onto other otherwise over people place quite rather really right said same saw say see seem seen
several shall should since some someone something soon still such take taken tell than that their them then there
these they thing think this those though three through thus time today together took toward under until upon
used using very want was well went were what when where whether which while whom whose will with within without
would year years yes your yours after amid among because been call called case city town village north south
east west central new old big small large green white black red blue yellow grey gray river lake hill hills
mountain mount valley field fields forest wood woods rock stone bridge road street way home house school church
market station camp base line front force forces army group party news post video photo photos live world state
states country land island port park garden king queen prince lord love hope faith star sun moon light dark night
day week month name word story report says said told asked reported killed killing attack attacks fire fight war
peace free open close green victory freedom liberty union spring summer autumn winter rose lion eagle wolf bear
fox mark john paul peter james jack jean rock hand head face body life death dead deaths dies died alive
""".split())

_lock = threading.Lock()
_dict = None            # cached read-only connection wrapper
_dict_sig = None


# --------------------------------------------------------------------------- #
# The read-only dictionary
# --------------------------------------------------------------------------- #

class Dict:
    """One open dictionary.db. Read-only + immutable (it never changes while open; we reopen if the
    file does). Safe for FastAPI's worker threads: every query runs under this object's lock."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.meta = {r[0]: r[1] for r in self.con.execute("SELECT key, value FROM meta")}
        self._keys, self._names, self._stats = {}, {}, None

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def by_key(self, key):
        """Entries with a name of this key: [{id, kind, country, category, label, admin1, rank,
        population, hit: [names that matched]}], best first. Cached (the file is immutable)."""
        if key not in self._keys:
            found = {}
            for r in self.rows("""SELECT e.id, e.kind, e.country, e.category, e.label, e.admin1, e.rank, e.population,
                                         n.name hit FROM names n JOIN entries e ON e.id = n.entry_id
                                  WHERE n.key = ? LIMIT 5000""", (key,)):
                e = found.setdefault(r["id"], {**{k: r[k] for k in r if k != "hit"}, "hit": []})
                e["hit"].append(r["hit"])
            out = sorted(found.values(), key=lambda e: (-(e["rank"] or 0), -(e["population"] or 0), e["id"]))
            if len(self._keys) > 20000:
                self._keys.clear()
            self._keys[key] = out
        return self._keys[key]

    def terms_by_head(self, key):
        """Lexicon TERMS with a multi-word name whose first word has this key (غاره -> غاره جويه), same shape as
        by_key. Used for inflected Arabic words that only occur as the head of a phrase in the lexicon."""
        ck = ("head", key)
        if ck not in self._keys:
            found = {}
            for r in self.rows("""SELECT e.id, e.kind, e.country, e.category, e.label, e.admin1, e.rank, e.population,
                                         n.name hit FROM names n JOIN entries e ON e.id = n.entry_id
                                  WHERE e.kind = 'term' AND n.key >= ? AND n.key < ? LIMIT 200""", (key + " ", key + "!")):
                e = found.setdefault(r["id"], {**{k: r[k] for k in r if k != "hit"}, "hit": []})
                e["hit"].append(r["hit"])
            self._keys[ck] = sorted(found.values(), key=lambda e: e["id"])
        return self._keys[ck]

    def names_of(self, eid):
        if eid not in self._names:
            if len(self._names) > 20000:
                self._names.clear()
            self._names[eid] = self.rows("SELECT name, lang, historic, expand, source FROM names WHERE entry_id = ?", (eid,))
        return self._names[eid]

    def entry(self, eid):
        r = self.rows("SELECT * FROM entries WHERE id = ?", (eid,))
        return r[0] if r else None

    def stats(self):
        if self._stats is None:
            by = lambda col, tbl: {(r["k"] or "-"): r["n"] for r in self.rows(
                f"SELECT {col} k, COUNT(*) n FROM {tbl} GROUP BY {col} ORDER BY n DESC")}
            self._stats = {"entries": self.rows("SELECT COUNT(*) n FROM entries")[0]["n"],
                           "names": self.rows("SELECT COUNT(*) n FROM names")[0]["n"],
                           "by_country": by("country", "entries"), "by_kind": by("kind", "entries"),
                           "by_lang": by("lang", "names")}
        return self._stats


def set_dictionary(path):
    """Use this dictionary.db (None: fall back to the LANGUAGE_PAIR_DICT environment variable)."""
    global _dict_path
    _dict_path = path


def get_dict():
    """The dictionary, or None when the file is missing/unreadable. Reopened if the file changed."""
    global _dict, _dict_sig
    path = _dict_path or os.environ.get(ENV_DICT)
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    sig = (path, st.st_mtime_ns, st.st_size)
    with _lock:
        if sig != _dict_sig:
            try:
                _dict, _dict_sig = Dict(path), sig
            except sqlite3.Error:
                _dict, _dict_sig = None, None
                return None
        return _dict


# --------------------------------------------------------------------------- #
# Caller edits (extra names, hidden names, extra entries)
# --------------------------------------------------------------------------- #

def _nk(name):
    return textnorm.normalize(name).strip()


class Edits:
    """Active (not undone) edits, replayed in order."""

    def __init__(self, rows):
        self.ids = [r["id"] for r in rows]
        self.hidden_entries, self.hidden_names = set(), set()
        self.added = {}                       # entry_id -> [{name, lang, edit_id}]
        self.user_entries = {}                # 'user:N' -> entry dict
        self.by_key = {}                      # key -> [entry_id] for user-added names
        for r in rows:
            a, eid = r["action"], r["entry_id"]
            if a == "add_entry":
                self.user_entries[eid] = {"id": eid, "kind": r["kind"] or "place", "country": r["country"],
                                          "category": r["category"], "label": r["label"], "admin1": None,
                                          "rank": 10, "population": None, "user": True, "edit_id": r["id"]}
            elif a == "add_name":
                self.added.setdefault(eid, []).append({"name": r["name"], "lang": r["lang"], "edit_id": r["id"]})
                self.hidden_names.discard((eid, _nk(r["name"])))
                key = translit.match_key(r["name"])
                if key:
                    self.by_key.setdefault(key, []).append(eid)
            elif a == "hide_name":
                self.hidden_names.add((eid, _nk(r["name"])))
            elif a == "hide_entry":
                self.hidden_entries.add(eid)

    def version(self):
        return hashlib.sha1(json.dumps(self.ids).encode()).hexdigest()[:8] if self.ids else ""


EDIT_ACTIONS = ("add_entry", "add_name", "hide_name", "hide_entry")


def load_edits(rows=None):
    """Edits from an iterable of row dicts {id, action, entry_id, name, lang, kind, country, category, label}
    (the caller's active edits in order), or none."""
    return Edits([dict(r) for r in rows or ()])


def version_of(d, ed):
    base = (d.meta.get("version") if d else None) or "none"
    return f"{base}+e{ed.version()}" if ed.ids else base


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #

def candidate_keys(toks):
    """Keys to try for a span of normalised tokens. A single Latin word may carry a joined article
    (alfashir, elgeneina): also try it without, if what remains is at least 4 letters."""
    keys = [translit.match_key(" ".join(toks))]
    if len(toks) == 1 and translit.script_of(toks[0]) == "la":
        w = translit.strip_marks(toks[0]).lower()
        for a in _ARTICLES:
            if w.startswith(a) and len(w) - len(a) >= 4:
                keys.append(translit.match_key(w[len(a):]))
                break
    return [k for k in dict.fromkeys(keys) if k]


def _stem_keys(w):
    """Match keys of a word's stems (Russian/Ukrainian Snowball / light stem; Arabic prefix + suffix stripped,
    also with the ة restored: غارات -> غار -> غاره), for the inflected-form lookup of lexicon terms."""
    out = []
    sc = translit.script_of(w)
    if sc == "cy":
        stems = [translit.cy_stem(w), _cy_stem(w, 5)]
    elif sc == "ar":
        p = textnorm.strip_prefix(w)
        x = translit.ar_suffix(p)
        stems = [p, x, x + "ه"]
    else:
        return out
    for st in stems:
        if st != w and len(st) >= 3:
            k = translit.match_key(st)
            if k and k not in out:
                out.append(k)
    return out


def _entries_for(key, d, ed):
    """Entries (dictionary + user-added) whose names have this key, minus what the caller hid."""
    out = []
    for e in (d.by_key(key) if d else []):
        if e["id"] in ed.hidden_entries:
            continue
        if all((e["id"], _nk(h)) in ed.hidden_names for h in e["hit"]):
            continue                          # every matching name was hidden
        out.append(e)
    seen = {e["id"] for e in out}
    for eid in dict.fromkeys(ed.by_key.get(key, [])):
        if eid in seen or eid in ed.hidden_entries:
            continue
        e = ed.user_entries.get(eid) or (d.entry(eid) if d else None)
        if e:
            out.append(e)
    out.sort(key=lambda e: (-(e.get("rank") or 0), -(e.get("population") or 0), e["id"]))
    return out


def entry_names(eid, d, ed):
    """All names of an entry as [{name, lang, historic, expand, hidden, user, edit_id?}]."""
    rows = [{"name": n["name"], "lang": n["lang"], "historic": bool(n["historic"]), "expand": bool(n["expand"]),
             "user": False} for n in (d.names_of(eid) if d and not eid.startswith("user:") else [])]
    rows += [{"name": n["name"], "lang": n["lang"], "historic": False, "expand": True, "user": True,
              "edit_id": n["edit_id"]} for n in ed.added.get(eid, [])]
    for r in rows:
        r["hidden"] = (eid, _nk(r["name"])) in ed.hidden_names
    return rows


def _detail(e, total=1):
    if total > 1:
        return f"{total} places named {e['label']}"
    bits = [e.get("category"), e.get("admin1"), e.get("country")]
    return " · ".join(str(b) for b in bits if b)


def _view(e):
    return {"id": e["id"], "label": e["label"], "category": e.get("category"), "country": e.get("country"),
            "admin1": e.get("admin1")}


# --------------------------------------------------------------------------- #
# FTS expressions for alternatives
# --------------------------------------------------------------------------- #

def _cy_stem(w, min_len):
    return w[:-1] if len(w) >= min_len and w[-1] in _INFLECT else w


SHORT = 3               # alt tokens up to this many characters (any script) match exactly, never as a prefix


def _alt_list(name):
    """FTS5 phrase expressions for one alternative name (empty list if unusable); OR them for a plain search,
    or use each inside NEAR(). Tokens of <= 3 characters (СВО, ГРУ, RPG, EW...) are exact: "сво"* would hit свои."""
    toks = textnorm.TOKEN.findall(textnorm.normalize(name))
    if not toks:
        return []
    if len(toks) == 1:
        w = toks[0]
        if len(w) <= SHORT:
            return [f'"{w}"']                                 # short (also Arabic <= 3): no prefix match
        if translit.script_of(w) == "cy":
            return [f'"{_cy_stem(w, 6)}"*']
        return textnorm.word_forms(w, stem=False)
    parts = []
    for i, w in enumerate(toks):
        if len(w) <= SHORT:
            parts.append(f'"{w}"')
        elif translit.script_of(w) == "cy":
            parts.append(f'"{_cy_stem(w, 4)}"*')              # "нов"* + "каховк"* (Нова Каховка / Новой Каховке)
        else:
            parts.append(f'"{w}"*' if i == len(toks) - 1 else f'"{w}"')
    exprs = [" + ".join(parts)]
    stripped = [textnorm.strip_prefix(w) if len(w) - len(textnorm.strip_prefix(w)) >= 2 else w for w in toks]
    if all(s != w for s, w in zip(stripped, toks)) and all(translit.script_of(w) == "ar" for w in toks):
        # every word carries an article: the `stems` column holds the stripped forms in order
        exprs.append(" + ".join(f'"{s}"*' if i == len(toks) - 1 and len(s) > SHORT else f'"{s}"'
                                for i, s in enumerate(stripped)))
    return exprs


def alt_fts(name):
    """FTS5 expression(s) for one alternative name, or None. See the module doc / spec, step 4."""
    ex = _alt_list(name)
    return None if not ex else "(" + " OR ".join(ex) + ")" if len(ex) > 1 else ex[0]


# --------------------------------------------------------------------------- #
# Expansion
# --------------------------------------------------------------------------- #

def _as_list(v):
    if isinstance(v, str):
        v = v.split(",")
    return [_nk(x) for x in (v or []) if x and x.strip()]


def dict_status(d="?"):
    """{available, key_version_ok, message?}: whether the place dictionary is installed and its keys match this
    version of the app. Carried on every expansion so the UI can say when matching is literal-only or stale."""
    if d == "?":
        d = get_dict()
    if not d:
        return {"available": False, "key_version_ok": False,
                "message": "No place dictionary is installed on this computer: only the words you typed (and their "
                           "Cyrillic spelling key) are searched, not other languages or spellings."}
    kv = d.meta.get("key_version")
    ok = str(kv) == str(translit.KEY_VERSION)
    out = {"available": True, "key_version_ok": ok}
    if not ok:
        out["message"] = (f"The dictionary was built with key version {kv if kv is not None else 'unknown'}, but this "
                          f"version of the library needs {translit.KEY_VERSION}: names in other spellings may not be found "
                          "until it is rebuilt (python -m language_pair_search.gazetteer_build).")
    return out


def from_params(params):
    """(enabled, drop, skip) from request params: expand=0, drop=a,b skip=x,y."""
    on = str(params.get("expand", "1")).strip().lower() not in ("0", "false", "off", "no")
    return on, params.get("drop") or "", params.get("skip") or ""


def expand(q, edits=None, doc_freq=None, enabled=True, drop=(), skip=()):
    """The expansion of a user query. Returns
    {"enabled", "dict_version", "fts", "groups": [...], "truncated"?}. `fts` is the expression to
    run (None for an empty query); with enabled=False it is the plain literal expression.
    `edits`: an Edits (or None). `doc_freq`: optional callable(token) -> share of documents (0..1) containing
    the token; without it only the stop-word list suppresses ordinary-word place names."""
    d, ed = get_dict(), edits if isinstance(edits, Edits) else load_edits(edits)
    parts = textnorm.fts_parts(q)
    literal = textnorm.fts_assemble("OR" if "op" in p else (p["expr"], p["neg"]) for p in parts)
    exp = {"enabled": bool(enabled), "dict_version": version_of(d, ed), "fts": literal, "groups": [],
           "dictionary": dict_status(d)}
    if not enabled or not literal:
        return exp
    drop, skip = set(_as_list(drop)), set(_as_list(skip))
    keep = {x[1:] for x in drop if x.startswith("+")}          # drop=+term restores a suppressed "common word" alt
    drop = {x for x in drop if not x.startswith("+")}
    items, groups, budget = [], [], [MAX_ALTS_TOTAL]
    truncated = False
    near_reduced = []

    def alt_view(a):
        """Public form of an alternative. A single-word place name that is an ordinary word (a stop word, or in
        more than 2% of posts, for entries ranked below 7) is suppressed - dropped with reason "common word" -
        unless the user restored it with drop=+term. Lexicon terms are never suppressed."""
        n, _, _, kind, rank = a
        k = _nk(n["name"])
        v = {"term": unicodedata.normalize("NFC", n["name"]), "lang": n["lang"], "historic": n["historic"],
             "dropped": k in drop}
        if kind == "place" and k not in keep and not v["dropped"] and _common_word(k, rank, doc_freq):
            v["dropped"], v["reason"] = True, "common word"
        return v

    def make_group(toks):
        """Group for this span of tokens, or None. Returns (public dict, [alt FTS expressions], [[alt phrases]]) or None."""
        nonlocal truncated
        span = " ".join(toks)
        found = []
        for key in candidate_keys(toks):
            found = _entries_for(key, d, ed)
            if found:
                break
        terms = [e for e in found if e["kind"] == "term"]
        if not found and len(toks) == 1:                       # обстрелом -> обстрел, الغارات -> غارة: lexicon TERMS only
            for key in _stem_keys(toks[0]):
                terms = [e for e in _entries_for(key, d, ed) if e["kind"] == "term"]
                if terms:
                    found = terms
                    break
            if not terms and d and translit.script_of(toks[0]) == "ar":     # الغارات: head of "غارات جوية"
                for key in _stem_keys(toks[0]):
                    terms = [e for e in d.terms_by_head(key) if e["id"] not in ed.hidden_entries]
                    if terms:
                        found = terms
                        break
        found = terms or found
        if not terms and len(toks) == 1 and translit.script_of(toks[0]) == "la":
            if len(toks[0]) < 4 or toks[0] in STOPWORDS:      # "Will", "Mark", "Hill": not a place
                found = []
        if not found:
            return None
        used = found[:MAX_ENTRIES]
        alts, seen = [], {span}
        for e in used:
            names = [n for n in entry_names(e["id"], d, ed) if n["expand"] and not n["hidden"]]
            names.sort(key=lambda n: (n["historic"], _LANG_ORDER.get(n["lang"], 9)))
            for n in names:
                k = _nk(n["name"])
                if k in seen:
                    continue
                seen.add(k)
                alts.append((n, alt_fts(n["name"]), _alt_list(n["name"]), e["kind"], e.get("rank") or 0))
        alts = [a for a in alts if a[1]]
        zz = None
        if len(toks) == 1 and translit.script_of(toks[0]) == "la":       # Legion -> zz key: finds Легион in OCR text
            w = toks[0]
            key = translit.latin_key(w)
            if len(w) >= 4 and w.isalpha() and w not in STOPWORDS and len(key) >= 3 and budget[0] > 0:
                term = f"Cyrillic ≈ {key}"
                zz = ({"name": term, "lang": "translit", "historic": False},
                      f'"{translit.ROMAN_PREFIX}{key}"*', [f'"{translit.ROMAN_PREFIX}{key}"*'], "translit", 0)
        room = max(0, min(MAX_ALTS_GROUP, budget[0]) - (1 if zz else 0))
        omitted = []
        if len(alts) > room:
            truncated = True
            omitted = [unicodedata.normalize("NFC", a[0]["name"]) for a in alts[room:]]     # cut: not searched
            alts = alts[:room]
        if zz:
            alts.append(zz)
        budget[0] -= len(alts)
        top = used[0]
        return ({"span": span, "kind": "term" if terms else "place", "label": top["label"],
                 "detail": _detail(top, len(found)) if not terms else (top.get("category") or ""),
                 "entries": [_view(e) for e in used], "more_entries": len(found) - len(used),
                 "alts": [alt_view(a) for a in alts], "omitted": omitted},
                [x[1] for x in alts], [x[2] for x in alts])

    def translit_group(w):
        """Cyrillic-romanisation group for a Latin word with no dictionary entry, or None."""
        key = translit.latin_key(w) if translit.script_of(w) == "la" else ""
        if len(w) >= 4 and w.isalpha() and w not in STOPWORDS and len(key) >= 3 and budget[0] > 0:
            term = f"Cyrillic ≈ {key}"
            g = {"span": w, "kind": "translit", "label": w, "detail": "matches the Cyrillic spelling",
                 "entries": [], "more_entries": 0,
                 "alts": [{"term": term, "lang": "translit", "historic": False, "dropped": _nk(term) in drop}]}
            budget[0] -= 1
            return g, [f'"{translit.ROMAN_PREFIX}{key}"*']
        return None

    def emit(g, exprs, toks):
        """Add a group's expression to the query; skipped/fully dropped groups stay literal."""
        orig = [textnorm.fts_word(w) for w in toks]
        orig = orig[0] if len(orig) == 1 else "(" + " AND ".join(orig) + ")"
        if g["span"] in skip:
            g["skipped"] = True
        live = [] if g.get("skipped") else [e for a, e in zip(g["alts"], exprs) if not a["dropped"]]
        items.append(("(" + " OR ".join([orig, *live]) + ")" if live else orig, False))

    def flush(run):
        i = 0
        while i < len(run):
            for L in range(min(MAX_SPAN, len(run) - i), 0, -1):
                toks = run[i:i + L]
                if not any(c.isalpha() for t in toks for c in t):
                    continue
                got = make_group(toks)
                if got:
                    groups.append(got[0])
                    emit(got[0], got[1], toks)
                    i += L
                    break
            else:
                w = run[i]
                i += 1
                got = translit_group(w)
                if got:
                    groups.append(got[0])
                    emit(got[0], got[1], [w])
                else:
                    items.append((textnorm.fts_word(w), False))

    def near_part(p):
        """`a NEAR/n b`: an OR of NEAR() combinations over each word operand's alternatives (FTS5 NEAR takes
        phrases only, no OR inside). Past MAX_NEAR combinations each operand is cut back to its most useful
        alternatives (original word, romanised key, then native-script names by entry rank, scripts alternating)
        and expansion.near_reduced lists what was used."""
        nonlocal near_reduced
        opts, labels = [], []
        for o in p["operands"]:
            if o["kind"] != "word" or len(o["words"]) != 1:
                opts.append([textnorm.near_operand_expr(o)])           # "phrases" and hyphenated words stay literal
                labels.append([" ".join(o["words"])])
                continue
            w = o["words"][0]
            forms = textnorm.word_forms(w)
            if len(forms) == 2 and translit._CYRILLIC.search(w):
                forms = forms[1:]                                # the stem prefix already covers the word
            cur = [(f, w) for f in forms]
            zz, native = [], []
            got = make_group([w])
            if got:
                g, _, lists = got
                if w in skip:
                    g["skipped"] = True
                groups.append(g)
                if not g.get("skipped"):
                    for a, lst in zip(g["alts"], lists):
                        if a["dropped"]:
                            continue
                        (zz if a["lang"] == "translit" else native).extend((x, a["term"]) for x in lst)
            elif (t := translit_group(w)):
                groups.append(t[0])
                if not (w in skip or t[0]["alts"][0]["dropped"]):
                    zz = [(t[1][0], t[0]["alts"][0]["term"])]
            sc = translit.script_of(w)
            by = {}
            for x, lab in native:                                # native scripts first, alternating between them
                k = translit.script_of(lab)
                by.setdefault(k if k in ("cy", "ar") and k != sc else "rest", []).append((x, lab))
            first = [v for k, v in by.items() if k != "rest"]
            mixed = [x for tup in itertools.zip_longest(*first) for x in tup if x]
            seen = set()
            allo = [t for t in cur + zz + mixed + by.get("rest", []) if not (t[0] in seen or seen.add(t[0]))]
            opts.append([x for x, _ in allo])
            labels.append([l for _, l in allo])
        total = 1
        for o in opts:
            total *= len(o)
        if total > MAX_NEAR:
            while total > MAX_NEAR:
                i = max(range(len(opts)), key=lambda k: len(opts[k]))
                total = total // len(opts[i]) * (len(opts[i]) - 1)
                opts[i].pop()
                labels[i].pop()
            near_reduced.append({"near": " NEAR ".join(o["words"][0] if len(o["words"]) == 1 else " ".join(o["words"])
                                                        for o in p["operands"]),
                                 "used": [{"operand": o["words"][0] if len(o["words"]) == 1 else " ".join(o["words"]),
                                           "alts": lab} for o, lab in zip(p["operands"], labels)]})
        exprs = [textnorm.near_expr(c, p["n"]) for c in itertools.product(*opts)]
        items.append(("(" + " OR ".join(exprs) + ")" if len(exprs) > 1 else exprs[0], False))

    run = []
    for p in parts:
        if "op" in p:
            flush(run); run = []
            items.append("OR")
        elif p["kind"] == "word" and not p["neg"]:
            run += p["words"]
        elif p["kind"] == "near":
            flush(run); run = []
            near_part(p)
        else:                                  # "phrases" and -negated words are never expanded
            flush(run); run = []
            items.append((p["expr"], p["neg"]))
    flush(run)
    exp["fts"] = textnorm.fts_assemble(items) or literal
    exp["groups"] = groups
    if truncated:
        exp["truncated"] = True
        exp["truncated_count"] = sum(len(g.get("omitted") or []) for g in groups)    # names cut, listed per group
    if near_reduced:
        exp["near_reduced"] = True             # a NEAR had > 24 combinations: operands cut back to their best alts
        exp["near_used"] = near_reduced
    return exp


def highlight_terms(exp, query):
    """Terms for highlighting: the words typed plus every live alternative (not the romanised keys)."""
    out = [t.rstrip("*") for t in (query or "").replace('"', " ").split()
           if t.upper() != "OR" and not t.startswith("-") and not re.fullmatch(r"NEAR(/\d+)?", t)]
    if exp and exp.get("enabled"):
        for g in exp["groups"]:
            if g.get("skipped") or g["kind"] == "translit":
                continue
            out += [a["term"] for a in g["alts"] if not a["dropped"] and a["lang"] != "translit"]
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------------- #
# Place mentions in text (used by the place tagger; a mention is a claim in the text, not a fact)
# --------------------------------------------------------------------------- #

PLACE_LANGS = ("ar", "ru", "uk", "en")
MAX_PLACE_SPAN = 5
RANK_KEEP = 7            # entries at or above this rank are tagged even when their name is a frequent word
MAX_LOW_CANDIDATES = 10  # a single word shared by more low-rank places than this is not tagged
FREQ_LIMIT = 0.02        # a single-token name in more than 2% of posts is an ordinary word, not a place
_pm = None               # cached place map: {"sig", "keys": key->(eid..), "firsts": set, "rank": {}, "ed": Edits}
_pm_lock = threading.Lock()
guard_stats = {"short": 0, "stopword": 0, "frequent": 0, "ambiguous": 0, "common": 0, "select": 0}     # mentions rejected by the tagging guards (running totals)


def _place_map(ed=None):
    """key -> entry ids for place names (expand=1, or lang ar/ru/uk/en), built lazily from dictionary.db plus
    the given Edits and rebuilt when either changes."""
    global _pm
    d = get_dict()
    if not d:
        return None
    ed = ed or Edits([])
    sig = (d.path, d.meta.get("version"), ed.version())
    pm = _pm
    if pm and pm["sig"] == sig:
        return pm
    with _pm_lock:
        if _pm and _pm["sig"] == sig:
            return _pm
        keys, rank, exact = {}, {}, {}
        info = {}                                 # entry id -> (curated or camp, category)
        country = {}                              # entry id -> ISO country code
        for r in d.rows("SELECT id, rank, category, sources, country FROM entries WHERE kind = 'place'"):
            rank[r["id"]] = r["rank"] or 0
            country[r["id"]] = r["country"]
            info[r["id"]] = ('"curated"' in (r["sources"] or "") or r["category"] == "camp", r["category"])
        terms = set()                             # single-token names of lexicon terms (СВО, ГРУ ...)
        for r in d.rows("SELECT n.name FROM names n JOIN entries e ON e.id = n.entry_id WHERE e.kind = 'term'"):
            t = textnorm.TOKEN.findall(_nk(r["name"]))
            if len(t) == 1:
                terms.add(t[0])
        langs = ",".join(f"'{l}'" for l in PLACE_LANGS)
        for r in d.rows(f"""SELECT n.key, n.entry_id, n.name FROM names n JOIN entries e ON e.id = n.entry_id
                            WHERE e.kind = 'place' AND (n.expand = 1 OR n.lang IN ({langs}))"""):
            if r["entry_id"] in ed.hidden_entries or (r["entry_id"], _nk(r["name"])) in ed.hidden_names or not r["key"]:
                continue
            keys.setdefault(r["key"], []).append(r["entry_id"])
            if " " not in r["key"] and translit.script_of(r["name"]) == "cy":     # exact spellings, see find_places
                exact.setdefault(_nk(r["name"]), set()).add(r["entry_id"])
        for eid, ue in ed.user_entries.items():
            if ue["kind"] == "place" and eid not in ed.hidden_entries:
                rank[eid] = ue.get("rank") or 10
                info[eid] = (True, ue.get("category"))
                country[eid] = None                # caller-added: no country rule applies
        for eid, names in ed.added.items():
            if eid in ed.hidden_entries or (eid.startswith("user:") and (eid not in ed.user_entries
                                                                          or ed.user_entries[eid]["kind"] != "place")):
                continue
            if not eid.startswith("user:") and eid not in rank:
                continue                          # an added name on a term entry is not a place
            for n in names:
                if (eid, _nk(n["name"])) not in ed.hidden_names:
                    k = translit.match_key(n["name"])
                    if k:
                        keys.setdefault(k, []).append(eid)
                        if " " not in k and translit.script_of(n["name"]) == "cy":
                            exact.setdefault(_nk(n["name"]), set()).add(eid)
        keys = {k: tuple(dict.fromkeys(v)) for k, v in keys.items()}
        firsts = {k.split(" ", 1)[0] for k in keys}
        _pm = {"sig": sig, "keys": keys, "firsts": firsts, "rank": rank, "ed": ed, "d": d, "exact": exact, "info": info, "terms": terms,
               "country": country}
        return _pm


# Ordinary Arabic / Russian / Ukrainian words that some place is also called (مدني = "civilian" is a Wad Madani
# name): never worth expanding a search to, whatever the entry's rank. Normalised forms.
COMMON_NON_EN = frozenset("""
    مدني جديد جديده الجديد الجديده سلام السلام شمال جنوب شرق غرب وسط حي مركز الحاله الشعبيه وحده الوحده النور الامل
    победа мир новый новая новое новые нове нова слобода село город поселок белые белый белая зеленый красный красная
    центр более был была были было быть который которая которое которые этот эта это эти этой того всех всего когда
    после перед между через только очень можно нужно россии украины
    перемога новий нова нове нові білий біла зелений червоний центр місто село були було була який яка яке які
""".split())


# Frequent ordinary words (~300 per language, normalised at load): a single-token Cyrillic/Arabic name that is one
# of these (or an inflection whose stem is) is never tagged as a place, whatever its rank.
_COMMON_RU = """
и в не на я что он с как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня еще нет о из ему
теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам сказал ведь там потом себя ничего ей
может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто человек чего раз тоже себе под жизнь будет ж тогда
кто этот говорил того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда
можно при наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем
хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между это которые который которая
которое которых которого которой которому очень также могут может был была были было будут стали стал стала стало новый новая
новое новые нового новой новых новом мирный мирные мирных мирное мирная белый белая белое белые белых зеленый красный красная
красное красные синий черный черные большой большая большое большие малый малая маленький старый старая старые молодой
северный северная северное северной северных южный южная южное южной южных западный западная западное западной восточный
восточная восточное восточной центральный центральная центральное центр центре центра центру город города городе городов
городу село села селе поселок район районе района области область областей области страна страны стране страну мир мира миру
война войны войне войну победа победы день дня дни дней год года году лет годы время времени раз часть части часть дело
дела место места вода воды земля земли земле рука руки голова дом дома доме улица улицы люди людей людям слово слова
работа работы база базы группа группы группе бригада бригады бригаду полк полка батальон рота команда канал канала
каналы атака атаки атаку удар удары ударов ударом обстрел обстрелы обстрела глубокая глубокий глубокое тихий тихая
веселое веселый золото золота золотой горка гора горы река реки озеро море поле лес степь мост станция вокзал
власть власти армия армии сила силы силой цель цели бой бои боях боевики боевиков боевые боевой ситуация вопрос
результат данные информация сообщает сообщили заявил заявили сказал сказали россия россии
""".split()
_COMMON_UK = """
і в не на я що він з як а то все вона так його але так ти до у же ви за би по тільки її мені було от від мене ще ні о з йому
тепер коли навіть ну раптом чи якщо вже або бути був була були було нього до вас нібито знову вам сказав адже там потім себе
нічого їй може вони тут де є треба нею для ми тебе їх чим сам без ніби людина чого раз теж собі під життя буде тоді хто цей
того тому цього який такий зовсім тут цьому один майже мій тим щоб неї зараз куди навіщо всіх ніколи можна при нарешті два
про інший хоч після над більше той через ці нас всього них яка багато невже три цю моя проте добре свою цієї перед іноді краще
трохи чому не можна більш завжди звичайно всю між це які який яка яке яких якого якій дуже також можуть новий нова нове нові
нового нової нових білий біла біле білі зелений червоний червона синій чорний великий велика мала малий старий старі молодий
північний північна південний південна західний західна східний східна центральний центр центрі центру місто міста місті
міст село села селі район районі області область країна країни країні мир миру війна війни війні перемога перемоги день
дня дні днів рік року роки років час часу часть частина частини справа справи місце місця вода води земля землі рука руки
голова дім дома вулиця вулиці люди людей слово слова робота роботи база бази група групи бригада бригади полк батальйон
рота команда канал канали атака атаки удар удари обстріл обстріли гора гори річка ріка річки озеро море поле ліс міст
станція вокзал влада армія армії сила сили ціль цілі бій бої бойовики бойові ситуація питання результат дані інформація
повідомляє повідомили заявив сказали україна україни
""".split()
_COMMON_AR = """
في من علي الي ان هذا هذه ذلك تلك التي الذي الذين هو هي هم نحن انا انت كان كانت كانوا يكون تكون يكن لم لن لا ما ماذا
كيف لماذا اين متي هل قد كل بعض غير بين بعد قبل عند عندما حتي حيث مع ضد عن او ام ثم لكن بل اذا اذ كما مثل نحو دون خلال
منذ لدي لدي فقط ايضا جدا كثير كبير كبيره صغير صغيره جديد جديده قديم قديمه اول اخر الاول الثاني الثالث الاخير الحاله
الحال الوضع الامر الامور الناس الشعب الشعبيه الشعبي الوطني الوطنيه العام العامه الخاص الخاصه الرئيس الوزير الوزراء
مجلس الحكومه الدوله الدول الجيش القوات القوه القوي الامن الامني الامنيه السلام الحرب الحروب الشهداء الشهيد الله
اللهم الحمد الرحمن الرحيم القدير العلي العظيم عزيز مدني مدنيه المدنيين المدنيون مدينه المدينه قريه القريه منطقه
المنطقه محليه المحليه ولايه الولايه الولايات محافظه المحافظه شمال الشمال جنوب الجنوب شرق الشرق غرب الغرب وسط الوسط
الشماليه الجنوبيه الشرقيه الغربيه الوسطي مركز المركز حي الحي شارع الشارع طريق الطريق جسر الجسر نهر النهر جبل الجبل
وادي الوادي بحر البحر ماء المياه الماء ارض الارض بيت البيت مدرسه المدرسه مستشفي المستشفي سوق السوق ميدان
يوم الايام اليوم امس غدا عام العام سنه السنه شهر الشهر اسبوع ساعه وقت الوقت مره مرات
قال قالت يقول قالوا اعلن اعلنت تعلن اكد اكدت اشار اشارت بعد وزاره الوزاره هيئه الهيئه لجنه اللجنه قايد القايد
قوات القوات فرقه الفرقه كتيبه الكتيبه اشراف وحده الوحده جهه الجهه دعم الدعم عمل العمل اجتماع الاجتماع
حمله الحمله برنامج البرنامج مشروع المشروع خدمه الخدمه صحه الصحه تعليم التعليم مياه الكهرباء
النور الامل الحريه العداله الوحده الاتحاد الاتحادي الاعلام الثقافه الرياضه التجاره الزراعه الزراعي المالي
احمد محمد علي عمر عثمان حسن حسين ابراهيم يوسف عبدالله خالد الامين مصطفي محمود عبدالرحمن ادم موسي عيسي
""".split()
_COMMON_AR_NAMES = """اسماعيل خالد صلاح جمال كمال طارق ناصر سعيد فاطمه زينب مريم هاشم بكري ياسر عادل ماجد فيصل يحيي
    زكريا سليمان داود هارون صالح اسحاق يعقوب ابوبكر عبدالعزيز عبدالكريم عبدالرحيم عبدالله بشير جعفر مالك وليد حمزه ايمن
    عماد رضوان ابراهيم يوسف موسي عيسي حسن حسين عثمان عمر علي احمد محمد اسامه بلال حامد هشام ياسين نصر ادريس اسماعيل""".split()
_COMMON_MISC = """свобода свободы свободе свободу широкий широкая широкое широком широким широких ровно ровный ровная
    берег берега берегов берегу полигон полигоны полигонах козлов вольный вольная солнечный солнечная тихий""".split()
_COMMON_NAMES = """александра анна мария елена ольга татьяна светлана ирина юлия екатерина константин вячеслав геннадий
    леонид валерий вадим станислав ярослав богдан тимур ринат ильяс али ахмед мухаммед мохаммед хасан хусейн ибрагим юсуф
    олена оксана наталія марія ірина юлія катерина тетяна світлана богдан ярослав вадим станіслав
    владимир александр сергей андрей дмитрий иван михаил алексей николай юрий игорь олег виктор евгений
    максим артем анатолий павел петр борис роман денис руслан василий григорий оксана наталья марина олена
    володимир олександр сергій андрій дмитро іван михайло олексій микола юрій ігор олег віктор євген максим""".split()
_COMMON_LATIN_NAMES = """ismail ismael mohamed mohammed muhammad mohammad ahmed ahmad ali omar umar osman othman uthman ibrahim
    yousif yousef yusuf youssef musa mousa moussa issa hassan hasan hussein husein khalid khaled salah abdallah abdullah
    adam idris idriss osama usama bilal hamid hisham yasin yassin nasr mustafa mostafa suleiman sulaiman daoud dawood""".split()
_LATIN_NAME_SET = frozenset(textnorm.normalize(w) for w in _COMMON_LATIN_NAMES)   # "Ismail" is a person, not Izmail
COMMON_WORDS = frozenset(textnorm.normalize(w) for w in _COMMON_RU + _COMMON_UK + _COMMON_AR + _COMMON_AR_NAMES + _COMMON_MISC
                         + _COMMON_NAMES + _COMMON_LATIN_NAMES)
HEAVY_CATEGORIES = frozenset("mountain landmark bridge river wadi station industrial military airport".split())


def _tag_common(tok):
    """Ordinary word (or inflection of one) that must never be tagged as a place."""
    if tok in COMMON_WORDS or textnorm.strip_prefix(tok) in COMMON_WORDS:
        return True
    return translit.script_of(tok) == "cy" and translit.cy_stem(tok) in COMMON_WORDS


def _in_common(w):
    """Word (or its stem / article-stripped form) is in COMMON_NON_EN."""
    return w in COMMON_NON_EN or textnorm.strip_prefix(w) in COMMON_NON_EN or (
        translit.script_of(w) == "cy" and translit.cy_stem(w) in COMMON_NON_EN)


def _common_word(name, rank=0, doc_freq=None):
    """True if `name` (normalised) is one token that is an ordinary word: a stop word (English list, or the small
    ar/ru/uk list above; any rank), or - for entries ranked below RANK_KEEP - present (also with the Arabic
    article removed) in more than FREQ_LIMIT of the posts. High-rank names stay: الخرطوم is in 30% of Sudanese posts."""
    toks = textnorm.TOKEN.findall(name)
    if len(toks) != 1:
        return False
    w = toks[0]
    if w in STOPWORDS or _in_common(w):
        return True
    return bool(doc_freq) and rank < RANK_KEEP and any(doc_freq(t) > FREQ_LIMIT for t in dict.fromkeys((w, textnorm.strip_prefix(w))))


def find_places(norm_text, edits=None, doc_freq=None):
    """Place-name mentions in NORMALISED text (textnorm.normalize output): [{entry_id, name (the words as written),
    start_tok, end_tok (exclusive), candidates}] - one item per candidate entry of a span, `candidates` = how many
    entries share it (>1: ambiguous). Longest span first (up to 5 tokens), left to right, no overlaps. Token
    indices count textnorm.TOKEN matches of norm_text. `edits` (an Edits) adds the caller's dictionary edits;
    `doc_freq` (callable(token) -> share of documents containing it) enables the frequent-word guard.
    Guards: a single-token name whose key is under 4 characters, a stopword, or (for entries ranked below 7) a word
    in more than 2% of posts is skipped - counted in guard_stats. [] if there is no dictionary."""
    pm = _place_map(edits)
    toks = textnorm.TOKEN.findall(norm_text or "")
    if not pm or not toks:
        return []
    keys, firsts, rank = pm["keys"], pm["firsts"], pm["rank"]
    wk = [translit.word_key(t) for t in toks]
    out, i, n = [], 0, len(toks)
    while i < n:
        hit = None
        for L in range(min(MAX_PLACE_SPAN, n - i), 0, -1):
            j = i + L
            if L == 1:
                cands = keys.get(wk[i])
                if cands is None and len(toks[i]) >= 6 and toks[i].startswith(_ART_HEADS):   # alfashir
                    cands = next((keys[k] for k in candidate_keys([toks[i]])[1:] if k in keys), None)
                if translit.script_of(toks[i]) == "cy":
                    # The key folds е/и and о/у (были ~ Биле, турецких ~ Торецк), so a Cyrillic word must be the
                    # entry's exact spelling; an inflected form (Бахмуте) may reach rank 7+ places via its stem.
                    ex = pm["exact"]
                    cands = tuple(e for e in cands or () if e in ex.get(toks[i], ()))
                    if not cands and len(toks[i]) >= 6 and not toks[i].endswith(_ADJ_ENDINGS):     # not украинские
                        # an adjective-like form (Красном море, Красное) must not reach a village named Красне:
                        # a stem match through such an ending needs a town-or-larger entry (rank 8+)
                        adj = toks[i].endswith(_ADJ_FORMS)
                        for w in (translit.cy_stem(toks[i]), _cy_stem(toks[i], 6)):
                            c = {e for suf in ("", *_INFLECT) for e in ex.get(w + suf, ())
                                 if rank.get(e, 0) >= (RANK_ADJ if adj else RANK_KEEP)}
                            if c and len(w) >= 5:
                                cands = tuple(sorted(c))
                                break
                if cands and ((translit.script_of(toks[i]) in ("cy", "ar") and (
                        toks[i] in pm["terms"] or _tag_common(toks[i]))) or toks[i] in _LATIN_NAME_SET):
                    guard_stats["common"] += 1                   # a lexicon term or an ordinary word: not a place
                    cands = None
                if cands:
                    sc = translit.script_of(toks[i])
                    ok = _select(_guard(cands, toks[i], wk[i], rank, doc_freq), True, pm, sc in ("cy", "ar"), sc)
                    hit = (j, ok) if ok else None
                break
            lo = i + 1 if translit.script_of(toks[i]) == "la" and toks[i] in translit._LAT_ARTICLE else i
            if wk[lo] not in firsts:                            # a leading Latin al-/el- is dropped, as in match_key
                continue
            cands = keys.get(" ".join(k for k in wk[lo:j] if k))
            ok = _select(cands or (), False, pm)
            if ok:
                hit = (j, ok)
                break
        if hit:
            j, ok = hit
            name = " ".join(toks[i:j])
            out += [{"entry_id": e, "name": name, "start_tok": i, "end_tok": j, "candidates": len(ok)} for e in ok]
            i = j
        else:
            i += 1
    return out


_ART_HEADS = tuple(translit._LAT_ARTICLE)
_ADJ_FORMS = ("ом", "ой", "ое", "ая", "ый", "ий", "ие", "ые", "ого", "ому", "ій", "не", "на", "ей", "ую", "юю", "ем",
              "ым", "им", "ых", "ими", "ыми", "ов", "ев", "ах", "ях")
RANK_ADJ = 8             # a Cyrillic stem match through an adjective-like ending needs at least this rank
RANK_AR_ANY = 9          # a single Arabic word may tag a place outside SD/TD only at this rank or above
RANK_CY_FOREIGN = 8      # a single Cyrillic word may tag a non-UA/RU place only at this rank or above
AR_HOME = frozenset({"SD", "TD"})
CY_HOME = frozenset({"UA", "RU", "BY"})
_ADJ_ENDINGS = ("ие", "ые", "ый", "ий", "ой", "ая", "ое", "их", "ых", "ими", "ыми", "ого", "его", "ему", "ому", "іх", "ій", "ому")


def _select(cands, single, pm, nonlatin=False, script=None):
    """Precision filter on a span's candidate entries. (1) a single word only tags rank 5+ (village and up),
    curated places and camps; (2) mountains, landmarks, bridges, rivers, wadis, stations, industrial, military and
    airports need a multi-word name, a curated entry or rank 7+; (3) more than 5 candidates: only rank 7+ ones
    are kept (none: the span is skipped). (4) a single Arabic, Cyrillic or Latin word also needs rank 7+ or a curated entry.
    (5) a city (rank 8+) beats smaller places of the same name."""
    rank, info = pm["rank"], pm["info"]
    out = []
    for e in cands:
        r, (cur, cat) = rank.get(e, 0), info.get(e, (True, None))
        if single and not (r >= 5 or cur):
            continue
        if not single and r < 5 and not cur:                  # multi-word neighbourhood/locality/hamlet names
            continue
        if single and cat in HEAVY_CATEGORIES and not (cur or r >= 7):
            continue
        if single and nonlatin and not (cur or r >= 7):      # ordinary words: Arabic/Cyrillic villages need a stronger
            continue                                          # signal
        if single and script == "la" and not (cur or r >= 7): # Latin keys are spelling-tolerant (e/i, o/u, articles fold),
            continue                                          # so "renew", "uobana" reached villages: towns and up only
        if single and script and not _script_affinity(script, pm["country"].get(e), cur, r):
            continue
        out.append(e)
    if len(out) > 5:
        out = [e for e in out if rank.get(e, 0) >= RANK_KEEP]
    if len(out) > 1:
        # prominence: a name shared by a city/region (rank 8+) and smaller places (7 or less) almost always means the
        # prominent one ("Воронеж": Voronezh, not the Ukrainian town Voronizh). Prominent entries stay ambiguous
        # among themselves (Mykolaiv city / Mykolaiv Oblast).
        if max(rank.get(e, 0) for e in out) >= 8:
            out = [e for e in out if rank.get(e, 0) >= 8]
    if len(out) < len(cands):
        guard_stats["select"] += 1
    return out


def _script_affinity(script, country, curated, r):
    """Script-country prior for a single-word match (a mention is a claim in the text, not a fact): an Arabic
    word is a Sudanese/Chadian place unless it is a well-known place (rank 9+); a Cyrillic word is Ukrainian/
    Russian/Belarusian unless the entry is prominent (rank 8+). Latin names keep the plain rules."""
    if script == "ar":
        return country in (None, *AR_HOME) or curated or r >= RANK_AR_ANY
    if script == "cy":
        return country in (None, *CY_HOME) or r >= RANK_CY_FOREIGN
    return True


def _guard(cands, tok, key, rank, doc_freq):
    """Entries of a span that survive the tagging guards. `tok` is set for single-token spans only."""
    if tok is None:
        return list(cands)
    if len(key) < 4:
        # short keys collide with everything, but must not hide capitals: "Kyiv"/"Київ"/"Киев" all key to "kiv".
        # A 4+ letter word may still tag a major place (rank 9+); anything smaller is dropped.
        major = [e for e in cands if rank.get(e, 0) >= 9] if len(tok) >= 4 else []
        if not major:
            guard_stats["short"] += 1
        return major
    low = [e for e in cands if rank.get(e, 0) < RANK_KEEP]
    keep = [e for e in cands if rank.get(e, 0) >= RANK_KEEP]
    if low:
        if tok in STOPWORDS or _in_common(tok):
            guard_stats["stopword"] += 1
            low = []
        elif doc_freq and doc_freq(tok) > FREQ_LIMIT:
            guard_stats["frequent"] += 1
            low = []
        elif not keep and len(low) > MAX_LOW_CANDIDATES:      # 40 hamlets called "Nove": says nothing
            guard_stats["ambiguous"] += 1
            low = []
    return [e for e in cands if e in keep or e in low]


def place(entry_id, edits=None):
    """{entry_id, label, country, category, admin1, lat, lon, rank} for a place entry (dictionary or
    caller-added), or None."""
    d = get_dict()
    e = (edits.user_entries.get(entry_id) if edits else None) or (
        d.entry(entry_id) if d and not (entry_id or "").startswith("user:") else None)
    if not e:
        return None
    return {"entry_id": entry_id, "label": e.get("label"), "country": e.get("country"), "category": e.get("category"),
            "admin1": e.get("admin1"), "lat": e.get("lat"), "lon": e.get("lon"), "rank": e.get("rank")}
