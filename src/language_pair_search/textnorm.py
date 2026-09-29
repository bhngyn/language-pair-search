"""
Text normalisation and FTS5 query building for cross-script (Arabic / Cyrillic / Latin) search.

normalize() is applied identically to documents and queries; index_stems() builds the `stems` column;
fts_query() turns a user query into a safe FTS5 expression. Stored text is never changed.
"""

import re
import unicodedata

from . import translit

_AR_MARKS = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
_INVISIBLE = "\u200b\u200c\u200d\u200e\u200f\u2060\u00ad\ufeff"     # zero-width, direction marks, soft hyphen
_TRANS = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه",
    "ک": "ك", "ی": "ي", "ە": "ه", "ۀ": "ه",            # Persian/Urdu variants -> Arabic letters
    "ё": "е", "Ё": "е",
    **{chr(0x0660 + i): str(i) for i in range(10)},   # Arabic-Indic digits
    **{chr(0x06F0 + i): str(i) for i in range(10)},   # Persian digits
    **{c: None for c in _INVISIBLE},
})
_AR_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال", "و", "ف", "ب", "ل", "ك", "س")
_ARABIC = re.compile("[؀-ۿ]")
TOKEN = re.compile(r"[\w؀-ۿ]+", re.U)

# ---- obfuscation folding (index time AND query time; stored text is never changed) ----
_LC = "a-z\u0400-\u04ff"                                   # Latin + Cyrillic letters (text is lowercased)
_PROTECT = re.compile(r"(?<!\S)(?:https?://|www\.|t\.me/|@)\S+|[\w.+-]+@[\w-]+(?:\.\w[\w-]*)+")   # urls, @users, e-mails
_LEET_AT = re.compile(rf"(?<=[{_LC}])[@$](?=[{_LC}])")           # w@gner, ca$h
_LEET_0 = re.compile(rf"(?<=[{_LC}])0(?!\d)|(?<!\d)0(?=[{_LC}])")  # b0mb; a lone 0 next to a letter, never inside numbers
_LEET_MAP = {"@": "a", "$": "s"}
_SPACED = re.compile(rf"(?<![^\W_])[{_LC}]([ \-_.*·•])(?:[{_LC}]\1){{2,}}[{_LC}](?![^\W_])")   # >=4 single letters, one separator
_SEPS = re.compile(r"[ \-_.*·•]")
_MIXED = re.compile(r"(?<![^\W_])(?=[^\W_]*[a-z])(?=[^\W_]*[\u0400-\u04ff])[^\W_]+")   # token with both Latin and Cyrillic
_REPEAT = re.compile(r"([^\W\d_])\1{2,}")                      # 3+ identical letters -> 1 (doubles are real)
_LAT_TWINS = "aeopcxykmtbhi"
_CYR_TWINS = "аеорсхукмтвні"
_TO_CYR = str.maketrans(_LAT_TWINS, _CYR_TWINS)
_TO_LAT = str.maketrans(_CYR_TWINS, _LAT_TWINS)


def _fix_mixed(m):
    """Homoglyph token (вagнер): map the minority script's look-alikes into the majority script."""
    w = m.group()
    cy = sum(1 for c in w if "\u0400" <= c <= "\u04ff")
    la = sum(1 for c in w if "a" <= c <= "z")
    return w.translate(_TO_CYR) if cy > la else w.translate(_TO_LAT) if la > cy else w


def _deobfuscate(t):
    if "@" in t or "$" in t:
        t = _LEET_AT.sub(lambda m: _LEET_MAP[m.group()], t)
    if "0" in t:
        t = _LEET_0.sub("o", t)
    t = _SPACED.sub(lambda m: _SEPS.sub("", m.group()), t)
    t = _MIXED.sub(_fix_mixed, t)
    return _REPEAT.sub(r"\1", t)


def normalize(text):
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = _AR_MARKS.sub("", t)
    t = t.translate(_TRANS).lower()
    if not ("@" in t or "://" in t or "www." in t or "t.me/" in t) or not _PROTECT.search(t):
        return _deobfuscate(t)
    out, pos = [], 0                                     # urls, @usernames and e-mails stay as written
    for m in _PROTECT.finditer(t):
        out.append(_deobfuscate(t[pos:m.start()]))
        out.append(m.group())
        pos = m.end()
    out.append(_deobfuscate(t[pos:]))
    return "".join(out)


def strip_prefix(tok):
    """Light Arabic stemming: drop one attached prefix (and/the/in/to/like/will)."""
    if not _ARABIC.match(tok):
        return tok
    for p in _AR_PREFIXES:
        if tok.startswith(p) and len(tok) - len(p) >= 3:
            return tok[len(p):]
    return tok


def stems(norm_text):
    out = []
    for tok in TOKEN.findall(norm_text):
        s = strip_prefix(tok)
        if s != tok:
            out.append(s)
    return " ".join(out)


_CYR_WORD = re.compile("[\u0400-\u04ff]+")
_tok_cache = {}


def _tok_stems(tok):
    """(prefix stem or None, [extra stems], romanised key or None) for one normalised token. Memoised: the
    vocabulary is small next to the token count, so reindexing 100k posts stays cheap."""
    r = _tok_cache.get(tok)
    if r is None:
        pre, extra, zz = None, [], None
        if _ARABIC.match(tok):
            s1 = strip_prefix(tok)
            pre = s1 if s1 != tok else None
            s2 = translit.ar_suffix(s1)
            if s2 != s1:
                extra.append(s2)
        elif _CYR_WORD.fullmatch(tok):
            st = translit.cy_stem(tok)
            if st != tok:
                extra.append(st)
        if len(tok) >= 3 and translit._CYRILLIC.search(tok):
            zz = translit.ROMAN_PREFIX + translit.cy_key(tok)
        r = (pre, tuple(extra), zz)
        if len(_tok_cache) > 300000:
            _tok_cache.clear()
        _tok_cache[tok] = r
    return r


def index_stems(norm_text):
    """The `stems` column: Arabic prefix-stripped tokens in text order (so phrases over them still work),
    then extra stems (Arabic light suffix, Russian/Ukrainian stems), then ROMAN_PREFIX keys of Cyrillic words."""
    pre, extra, zz = [], {}, {}
    for tok in TOKEN.findall(norm_text):
        p, ex, z = _tok_stems(tok)
        if p:
            pre.append(p)
        for e in ex:
            extra[e] = 1
        if z:
            zz[z] = 1
    return " ".join([*pre, *extra, *zz])


def _star(x):
    """A stem as a query term: prefix match, except 3-letter stems (too many words start with them)."""
    return f'"{x}"*' if len(x) >= 4 else f'"{x}"'


def word_forms(w, stem=True):
    """Query forms of one plain word: [typed word, article-stripped Arabic, suffix-stripped Arabic / Russian or
    Ukrainian stem], each an FTS term. Same stemming as the `stems` column, so inflected forms meet."""
    forms = [f'"{w}"*']
    if _ARABIC.match(w):
        s = strip_prefix(w)
        if s != w and len(w) - len(s) >= 2:      # query side only drops the article family (ال، وال، بال…);
            forms.append(f'"{s}"*')              # a single leading letter may belong to the root (فاشر)
        else:
            s = w
        x = translit.ar_suffix(s) if stem else s
        if x != s:
            forms.append(_star(x))
    elif stem and _CYR_WORD.fullmatch(w):
        st = translit.cy_stem(w)
        if st != w:
            forms.append(_star(st))
    return forms


def fts_word(w, stem=True):
    """FTS5 expression for one plain query token (prefix match; article-stripped / stemmed alternatives).
    stem=False (used for -excluded words) leaves the stems out, so an exclusion never hides more than was typed."""
    f = word_forms(w, stem)
    return f[0] if len(f) == 1 else "(" + " OR ".join(f) + ")"


_NEAR_RE = re.compile(r"NEAR(?:/([0-9]{1,4}))?")   # upper case only: "near" alone is a real word
_NEAR_MARK = re.compile("\ue000([0-9]+)\ue001")
DEFAULT_NEAR = 10


def near_operand_expr(o):
    """Literal FTS phrase for one NEAR operand: a word is prefix-matched, a "phrase" exact (or prefix with a trailing *)."""
    if o["kind"] == "phrase":
        return '"' + " ".join(o["words"]) + '"' + ("*" if o.get("prefix") else "")
    return '"' + " ".join(o["words"]) + '"*'


def near_expr(exprs, n):
    return f"NEAR({' '.join(exprs)}, {n})"


def fts_parts(q):
    """Split a user query into parts: {"op": "OR"} or {"kind": "word"|"phrase", "neg": bool,
    "words": [tokens], "expr": the part's own FTS expression}, or (for `a NEAR/n b`)
    {"kind": "near", "neg": False, "operands": [{"kind", "words", "prefix"?}], "n": int, "words": [...],
    "expr": literal NEAR(...)}. `fts_assemble` joins them."""
    # NEAR is only a keyword outside "quotes": mark it before normalising (which lower-cases it)
    q = normalize(" ".join(
        f"\ue000{m.group(1) or DEFAULT_NEAR}\ue001" if not p.startswith('"') and (m := _NEAR_RE.fullmatch(p)) else p
        for p in re.findall(r'"[^"]*"\*?|\S+', q or ""))).strip()
    out = []
    for p in re.findall(r'"[^"]*"\*?|\S+', q):
        if p.upper() == "OR":
            out.append({"op": "OR"})
            continue
        m = _NEAR_MARK.fullmatch(p)
        if m:
            out.append({"op": "NEAR", "n": min(int(m.group(1)), 1000)})
            continue
        neg = p.startswith("-") and len(p) > 1
        if neg:
            p = p[1:]
        words = TOKEN.findall(p)
        if not words:
            continue
        if p.startswith('"'):
            out.append({"kind": "phrase", "neg": neg, "words": words, "expr": '"' + " ".join(words) + '"',
                        "prefix": p.endswith("*")})
        else:
            each = [fts_word(w, not neg) for w in words]
            out.append({"kind": "word", "neg": neg, "words": words,
                        "expr": each[0] if len(each) == 1 else "(" + " AND ".join(each) + ")"})
    return _fold_near(out)


def _fold_near(parts):
    """Fold `a NEAR/n b [NEAR/m c]` into one "near" part. A NEAR without two plain operands is dropped."""
    out, i = [], 0
    while i < len(parts):
        p = parts[i]
        if p.get("op") == "NEAR":
            prev = out[-1] if out else None
            nxt = parts[i + 1] if i + 1 < len(parts) else None
            if prev and nxt and "kind" in nxt and not nxt["neg"] and nxt["kind"] != "near" \
                    and prev["kind"] in ("word", "phrase", "near") and not prev["neg"]:
                if prev["kind"] != "near":
                    out[-1] = prev = {"kind": "near", "neg": False, "operands": [prev], "n": p["n"], "words": list(prev["words"])}
                prev["operands"].append(nxt)
                prev["n"] = max(prev["n"], p["n"])
                prev["words"] += nxt["words"]
                prev["expr"] = near_expr([near_operand_expr(o) for o in prev["operands"]], prev["n"])
                i += 2
                continue
            i += 1
            continue
        if p.get("kind") == "near":
            p = dict(p, expr=near_expr([near_operand_expr(o) for o in p["operands"]], p["n"]))
        out.append(p)
        i += 1
    for p in out:                                    # a lone marker never survives; set the literal expr
        if p.get("kind") == "near" and "expr" not in p:
            p["expr"] = near_expr([near_operand_expr(o) for o in p["operands"]], p["n"])
    return [p for p in out if p.get("op") != "NEAR"]


def fts_assemble(items):
    """items: "OR" or (expr, negated). Same joining rules as always: no leading NOT, no dangling OR/NOT."""
    out = []
    for it in items:
        if it == "OR":
            if out and out[-1] != "OR":
                out.append("OR")
            continue
        expr, neg = it
        if neg:
            if not out or out[-1] == "OR":
                continue                      # FTS5 can't start with NOT
            out.append("NOT")
        out.append(expr)
    while out and out[-1] in ("OR", "NOT"):
        out.pop()
    return " ".join(_and_join(out)) or None


def fts_query(q):
    """User query -> safe FTS5 expression (literal: no dictionary expansion, see lexicon.expand).

    - words are ANDed; each is prefix-matched against text and stems (plus its Arabic/Russian/Ukrainian stem)
    - "quoted phrases" match exactly
    - OR between terms, and -word to exclude
    - a NEAR/10 b: both within 10 tokens (NEAR alone = 10); operands are words or "phrases"
    """
    return fts_assemble("OR" if "op" in p else (p["expr"], p["neg"]) for p in fts_parts(q))


def fts_text(expr):
    """Restrict an FTS5 expression to the text columns (norm, stems) of posts_fts / comments_fts, so a search
    never matches the `meta` column (channel handle/title, forward names, hashtags). Applied at match time, so
    frozen/stored expressions stay as they were saved."""
    return "{norm stems} : (" + expr + ")"


def fts_names(expr):
    """The same expression restricted to the `meta` column (channel and forward names): the opt-in in=names source."""
    return "{meta} : (" + expr + ")"


def fts_scoped(expr, text=True, names=False):
    """Expression for posts_fts / comments_fts: text columns, names column, or either."""
    parts = ([fts_text(expr)] if text else []) + ([fts_names(expr)] if names else [])
    return " OR ".join(parts) if len(parts) > 1 else (parts[0] if parts else None)


def _and_join(tokens):
    res = []
    for t in tokens:
        if res and res[-1] not in ("OR", "NOT") and t not in ("OR", "NOT"):
            res.append("AND")
        res.append(t)
    return res


