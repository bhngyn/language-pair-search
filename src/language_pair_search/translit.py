"""
Script-independent keys for cross-script search.

Two uses:
  latin_key / cy_key  fold a Latin or Cyrillic word into one shared "key" alphabet, so
                      Kyiv / Kiev / Київ / Киев all become "kiv", Artyomovsk / Artemivsk /
                      Артемовск become "artimuvsk", Kharkiv / Харків become "qarkiv".
                      The search index stores ROMAN_PREFIX + cy_key(word) for every Cyrillic
                      word, and a Latin query word also looks for ROMAN_PREFIX + latin_key(word),
                      so Latin input finds Cyrillic text with no dictionary entry.
  match_key           the lookup key for a whole name (any script) in the gazetteer/lexicon.
                      Latin and Cyrillic go through the key alphabet; Arabic is normalised and
                      loses its article (ال، وال، بال…), as does a leading Latin al-/el-.

Keys are deliberately lossy (e/i/y and o/u fold together, doubled letters collapse): they
are for finding candidates, which the user sees and can remove. Arabic is never
romanised: vowels aren't written, so a romanisation would be guesswork.
"""

import re
import unicodedata

ROMAN_PREFIX = "zz"            # marks romanised tokens in the FTS `stems` column
# Bump whenever match_key output can change (here or in textnorm.normalize): dictionary.db records the
# version it was built with, and a mismatch means its names.key values are stale -> rebuild.
KEY_VERSION = 2      # 2: textnorm.normalize gained obfuscation folding (leet, homoglyphs, Persian letters, repeats)

_CY = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "ё": "e", "є": "ie",
    "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "q",
    "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "i", "ь": "", "э": "e",
    "ю": "iu", "я": "ia", "ў": "u",
}
# Latin digraphs first (longest first), then single letters. "q" stands for х/kh.
_LAT_MULTI = [("shch", "shch"), ("tch", "ch"), ("sch", "shch"), ("kh", "q"), ("zh", "zh"),
              ("ch", "ch"), ("sh", "sh"), ("ts", "ts"), ("tz", "ts"), ("ph", "f"), ("ou", "u")]
_LAT_ONE = {"q": "k", "h": "g", "x": "ks", "c": "k", "w": "v", "j": "i", "y": "i"}
_VOWELS = "aeiouy"
_FOLD_VOWELS = str.maketrans({"e": "i", "o": "u"})

_CYRILLIC = re.compile("[Ѐ-ӿ]")
_ARABIC = re.compile("[؀-ۿ]")
_LATIN = re.compile("[a-z]")
_APOS = re.compile("[’'ʼʻ`ʿʾ‘´]")
_AR_ARTICLE = ("وال", "بال", "فال", "كال", "لل", "ال")
_LAT_ARTICLE = {"al", "el", "ad", "ed", "ar", "er", "as", "es", "at", "et", "an", "en", "az", "ez",
                "ash", "esh", "adh", "ath", "ad", "ud", "ul", "ur"}


def _finish(s):
    s = s.translate(_FOLD_VOWELS)
    return re.sub(r"(.)\1+", r"\1", s)                    # collapse doubled letters


def strip_marks(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def cy_key(word):
    """Cyrillic word (Russian or Ukrainian, any case) -> key. Non-Cyrillic letters pass through."""
    w = word.lower().replace("ё", "е")
    return _finish("".join(_CY.get(c, c) for c in w if c.isalnum()))


def latin_key(word):
    """Latin word (any transliteration convention, diacritics allowed) -> key."""
    w = _APOS.sub("", strip_marks(word).lower())
    w = re.sub(r"(?<=[aeiou])y(?=[aeiou])", "", w)       # Mykolayiv/Nikolayev ~ Миколаїв/Николаев
    w = re.sub(r"^y(?=[ao])", "i", w)                      # Yalta, Yasinuvata keep a vowel
    w = w.replace("yo", "e").replace("jo", "e")            # Artyomovsk ~ Артемовск (ё is written е)
    out, i = [], 0
    while i < len(w):
        for a, b in _LAT_MULTI:
            if w.startswith(a, i):
                out.append(b)
                i += len(a)
                break
        else:
            c = w[i]
            if c.isalnum():
                out.append(_LAT_ONE.get(c, c))
            i += 1
    return _finish("".join(out))


def script_of(word):
    if _ARABIC.search(word):
        return "ar"
    if _CYRILLIC.search(word):
        return "cy"
    if _LATIN.search(strip_marks(word).lower()):
        return "la"
    return ""


def word_key(word):
    """Key for one token of any script."""
    s = script_of(word)
    if s == "cy":
        return cy_key(word)
    if s == "la":
        return latin_key(word)
    if s == "ar":
        for p in _AR_ARTICLE:
            if word.startswith(p) and len(word) - len(p) >= 2:
                return word[len(p):]
        return word
    return word.lower()


def tokens(text):
    """Normalised tokens, as the search index sees them (hyphens and apostrophes split/join like it)."""
    from .textnorm import normalize, TOKEN       # late import: textnorm imports this module
    t = _APOS.sub("", strip_marks(text)) if not _ARABIC.search(text) else text
    return TOKEN.findall(normalize(t))


def match_key(name):
    """Lookup key for a whole name: El Fasher = Al-Fashir = الفاشر? No: Latin and Arabic keys
    differ (Arabic isn't romanised); the dictionary links them. Within a script family the key
    absorbs spelling variation: El Fasher = Al-Fashir = Alfashir* ; Kyiv = Kiev = Київ = Киев.
    (*joined articles are handled at lookup time, see lexicon.candidate_keys.)"""
    toks = tokens(name)
    if len(toks) > 1 and script_of(toks[0]) == "la" and toks[0] in _LAT_ARTICLE:
        toks = toks[1:]
    return " ".join(k for k in (word_key(t) for t in toks) if k)


def romanised_tokens(norm_text):
    """ROMAN_PREFIX+key for each distinct Cyrillic word (3+ letters) in already-normalised text."""
    from .textnorm import TOKEN
    seen, out = set(), []
    for tok in TOKEN.findall(norm_text):
        if len(tok) >= 3 and _CYRILLIC.search(tok):
            k = ROMAN_PREFIX + cy_key(tok)
            if k not in seen:
                seen.add(k)
                out.append(k)
    return out


# --------------------------------------------------------------------------- #
# Stemmers (index side: extra tokens in the `stems` column; query side: `stem`* alternatives)
# --------------------------------------------------------------------------- #

# Arabic light suffixes, longest first (text is normalised: ة is already ه). ت / وا are verb endings
# (قصفت / قصفوا -> قصف), added to the spec's list so the past-tense forms meet their stem.
_AR_SUFFIXES = ("ات", "ون", "ين", "ان", "ها", "هم", "هن", "كم", "نا", "يه", "وا", "ية", "ه", "ة", "ي", "ت")


def ar_suffix(tok):
    """Drop one light Arabic suffix if at least 3 letters remain."""
    for s in _AR_SUFFIXES:
        if tok.endswith(s) and len(tok) - len(s) >= 3:
            return tok[:-len(s)]
    return tok


_RU_VOW = "аеиоуыэюя"
_RU_PERF1 = ("вшись", "вши", "в")                               # need а/я before
_RU_PERF2 = ("ившись", "ывшись", "ивши", "ывши", "ив", "ыв")
_RU_ADJ = ("ими", "ыми", "его", "ого", "ему", "ому", "ее", "ие", "ые", "ое", "ей", "ий", "ый", "ой", "ем", "им",
           "ым", "ом", "их", "ых", "ую", "юю", "ая", "яя", "ою", "ею")
_RU_PART1 = ("ем", "нн", "вш", "ющ", "щ")                      # need а/я before
_RU_PART2 = ("ивш", "ывш", "ующ")
_RU_VERB1 = ("ете", "йте", "нно", "ешь", "ла", "на", "ли", "ло", "но", "ет", "ют", "ны", "ть", "ем", "й", "л", "н")
_RU_VERB2 = ("ейте", "уйте", "ила", "ыла", "ена", "ите", "или", "ыли", "ило", "ыло", "ено", "ует", "уют", "ены",
             "ить", "ыть", "ишь", "ей", "уй", "ил", "ыл", "им", "ым", "ен", "ят", "ит", "ыт", "ую", "ю")
_RU_NOUN = ("иями", "ями", "ами", "иям", "иях", "ией", "ием", "ие", "ье", "еи", "ии", "ей", "ой", "ий", "ям", "ем",
            "ам", "ом", "ах", "ях", "ию", "ью", "ия", "ья", "ев", "ов", "а", "е", "и", "й", "о", "у", "ы", "ь", "ю", "я")


def _ends(w, rv, group, need_ay=False):
    """Longest ending of `group` that lies inside RV (and, for the а/я groups, follows а or я inside RV)."""
    best = ""
    for e in group:
        if len(e) > len(best) and w.endswith(e):
            i = len(w) - len(e)
            if i >= rv and (not need_ay or (i - 1 >= rv and w[i - 1] in "ая")):
                best = e
    return best


def ru_stem(w):
    """Snowball Russian stemmer (public algorithm, pure Python). Input: lowercase, ё already folded to е."""
    n = len(w)
    rv = r1 = r2 = n
    for i, c in enumerate(w):
        if c in _RU_VOW:
            rv = i + 1
            break
    seen_v = False
    for i, c in enumerate(w):                                  # R1: after the first non-vowel following a vowel
        if c in _RU_VOW:
            seen_v = True
        elif seen_v:
            r1 = i + 1
            break
    seen_v = False
    for i in range(r1, n):                                     # R2: same inside R1
        if w[i] in _RU_VOW:
            seen_v = True
        elif seen_v:
            r2 = i + 1
            break

    def cut(e):
        return w[:len(w) - len(e)]

    e = _ends(w, rv, _RU_PERF1, True) or _ends(w, rv, _RU_PERF2)
    if e:
        w = cut(e)
    else:
        e = _ends(w, rv, ("ся", "сь"))
        if e:
            w = cut(e)
        e = _ends(w, rv, _RU_ADJ)
        if e:                                                  # adjectival = adjective + optional participle
            w = cut(e)
            e = _ends(w, rv, _RU_PART1, True) or _ends(w, rv, _RU_PART2)
            if e:
                w = cut(e)
        else:
            e = _ends(w, rv, _RU_VERB1, True) or _ends(w, rv, _RU_VERB2)
            if not e:
                e = _ends(w, rv, _RU_NOUN)
            if e:
                w = cut(e)
    if w.endswith("и") and len(w) > rv:
        w = w[:-1]
    for d in ("ость", "ост"):                                  # derivational, only if the ending starts in R2
        if w.endswith(d) and len(w) - len(d) >= r2:
            w = w[:-len(d)]
            break
    if w.endswith("ейше"):
        w = w[:-4]
    elif w.endswith("ейш"):
        w = w[:-3]
    if w.endswith("нн"):
        w = w[:-1]
    elif w.endswith("ь"):
        w = w[:-1]
    return w


_UK_ENDINGS = ("ього", "ьому", "ами", "ями", "ові", "еві", "ого", "ому", "ими", "іми", "ати", "яти", "ити", "ють",
               "ять", "ать", "ить", "уть", "ів", "їв", "ий", "ій", "ої", "ою", "ею", "єю", "ем", "єм", "ам", "ям",
               "ах", "ях", "ая", "яя", "ую", "юю", "ає", "яє", "ює", "ує", "ла", "ло", "ли", "а", "я", "у", "ю",
               "е", "є", "и", "ї", "і", "о", "ь", "й")
_UK_LETTERS = re.compile("[іїєґ]")


def uk_stem(w):
    """Light Ukrainian stripper: reflexive ся/сь, then the longest common noun/adjective/verb ending."""
    for r in ("ся", "сь"):
        if w.endswith(r) and len(w) - 2 >= 4:
            w = w[:-2]
            break
    for e in _UK_ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 4:
            return w[:-len(e)]
    return w


_stem_cache = {}


def cy_stem(w):
    """Stem of a normalised Cyrillic word (Ukrainian if it has і ї є ґ, else Russian Snowball). Returns the
    word itself when there is no stem worth indexing (unchanged or under 4 letters)."""
    s = _stem_cache.get(w)
    if s is None:
        s = uk_stem(w) if _UK_LETTERS.search(w) else ru_stem(w)
        if len(s) < 4 or s == w:
            s = w
        if len(_stem_cache) > 300000:
            _stem_cache.clear()
        _stem_cache[w] = s
    return s
