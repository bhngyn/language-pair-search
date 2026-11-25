# language-pair-search

Cross-script search for Arabic / Russian / Ukrainian ↔ English text, extracted from the Telegram Investigator
project so it can be used on its own. Pure Python standard library, SQLite FTS5.

A search for `Bakhmut` also finds `Бахмут`, `Артёмовск` (the Soviet name) and romanised spellings; `El Fasher`
also finds `الفاشر`, `Alfashir`, `Al-Fashir`; `airstrike` finds `авиаудар` and `غارة جوية`. Expansion is
transparent: the result lists every alternative as a removable group, and the exact FTS5 expression that ran, so a
search can be recorded and re-run identically.

## Layout

| Module | What it does |
|---|---|
| `textnorm` | `normalize()` (Arabic marks/letter variants, invisible chars, obfuscation folding such as `в а г н е р`, `w@gner`, homoglyphs), Arabic prefix stemming, `index_stems()`, and the FTS5 query builder (`fts_query`, `fts_parts`; `OR`, `-word`, `"phrases"`, `a NEAR/5 b`) |
| `translit` | Rule-based Cyrillic romanisation keys (`match_key`), Russian/Ukrainian/Arabic light stemmers. `KEY_VERSION` must match the dictionary and any index built from it |
| `index` | The FTS5 table layout the query builder expects (`fts_ddl`) and `index_text` / `index_row` |
| `lexicon` | `expand()` (dictionary expansion), `find_places()` (place mentions in text), `place()`, `Edits` (your own added/hidden names and entries) |
| `entities` | `extract()`: phone numbers, crypto addresses, bank cards (Luhn), unit numbers, callsigns, vehicle plates |
| `gazetteer_build` | Builds `dictionary.db` from GeoNames + OSM + the curated lists + the term lexicons |
| `js/lpsq.mjs` | JavaScript port of the query side (`normalize`, `matchKey`, `ftsQuery`, `ftsScoped`, `expand`), kept in parity by golden tests; see "JavaScript query port" |

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python tests/test_search_core.py && .venv/bin/python tests/test_entities.py
```

```python
import sqlite3
import language_pair_search as lps

lps.set_dictionary("dictionary.db")           # or set LANGUAGE_PAIR_DICT; see "The dictionary" below

con = sqlite3.connect("search.db")
con.execute(lps.fts_ddl("posts_fts"))
lps.index_text(con, "posts_fts", 1, "Обстрел Артёмовска, في الفاشر")   # rowid = your own document id
con.commit()

exp = lps.expand("Bakhmut NEAR airstrike")     # {"fts": ..., "groups": [...], "dict_version": ...}
rows = con.execute("SELECT rowid FROM posts_fts WHERE posts_fts MATCH ?", (lps.textnorm.fts_scoped(exp["fts"]),))
```

- Without a dictionary, `expand()` still adds the Cyrillic-romanisation alternatives; `find_places()` returns `[]`.
- `lps.fts_query("wagner NEAR/5 bakhmut")` gives the literal expression with no expansion.
- The `meta` column (`fts_ddl(table, meta=True)`) is for names such as channel or author; `fts_scoped` keeps a text search from matching it.
- `fts_ddl(table, contentless=True)` builds the same index without storing a copy of the text (about half the size;
  needs SQLite ≥ 3.43). Matching, `bm25()` and `index_text` replacement work as before; `snippet()`/`highlight()` and
  reading the columns back do not, so keep the original text in your own table.
- `expand(q, edits=Edits(rows), doc_freq=fn)`: `edits` are your extra/hidden names and entries (row dicts with `id`, `action` in `add_entry | add_name | hide_name | hide_entry`, `entry_id`, `name`, `lang`, `kind`, `country`, `category`, `label`); `doc_freq(token) -> 0..1` (share of your documents containing the token) lets the ordinary-word guard also suppress place names that are common in *your* corpus.
- Store the `expansion` with a saved search or alert rule if it must not change when the dictionary is edited later.

## The dictionary

`dictionary.db` (about 50 MB, ODbL) is **not in this repository**. Either build it (needs the raw GeoNames / Geofabrik
downloads; steps in [`src/language_pair_search/data/gazetteer/README.md`](src/language_pair_search/data/gazetteer/README.md)):

```bash
.venv/bin/python -m language_pair_search.gazetteer_build            # add --no-osm for GeoNames + curated + lexicon only
```

or copy an already built file. Coverage: Ukraine (ru/uk ↔ en, including Russian/Soviet exonyms) and Sudan (ar ↔ en,
many English spellings per place). The term lexicons (`data/lexicon/`) contain slurs and propaganda vocabulary on
purpose, marked in each entry's notes.

## JavaScript query port

`js/lpsq.mjs` is a dependency-free ES module that ports the **query side** to the browser. A page can build the same
FTS5 `MATCH` expression Python builds, for example against an SQLite database opened with sqlite-wasm, over an index
written in Python with `index_text`.

Exports: `normalize(text)`, `matchKey(name)`, `ftsQuery(q)`, `ftsScoped(expr, text = true, names = false)`,
`expand(q, {enabled, drop, skip})` (behaves like `lexicon.expand` with no `dictionary.db`), `KEY_VERSION`,
`FTS_VERSION`, `ROMAN_PREFIX`, and `LpsQueryError` (kept for callers that catch it; nothing throws it now).

### Parity tests

```bash
.venv/bin/python scripts/golden.py              # writes tests/golden/lps_query.json (git-ignored, ~10 MB, ~80k vectors)
node --test 'tests/js/*.test.mjs'               # JS must reproduce every vector; prints the first 20 mismatches per section
```

Node 22 does not accept a bare directory (`node --test tests/js/` fails), so use the glob form above.

The generator runs this checkout's Python and records its outputs for:
- `normalize`, `match_key`, `fts_query`, `fts_scoped`;
- `expand`, including the `fts` string, the `groups`, and the `drop`/`skip`/`enabled` options;
- a code-point sweep: `normalize(ch)`, `match_key("ab"+ch+"cd")` and `fts_query("ab"+ch+"cd")` for ~23k code points.

Its inputs are synthetic word lists in many scripts, personal-name variants, and the names in this repository's own
lexicons and curated place lists. It refuses to run if a `dictionary.db` is configured. The test compares JSON text, so
key order counts too. It also checks the embedded Unicode tables, every table retyped from Python (stemmer endings,
articles, transliteration maps, the name folds, `_TRANS`, `STOPWORDS`, limits) and the version constants.

**Any change** to `normalize`, the keys, the stemmers, `fts_query` or `expand` must be ported to `lpsq.mjs` in the same PR.
Regenerate the goldens and keep the test at zero mismatches. If the Python Unicode version changes, print the tables with
`python scripts/golden.py --tables` and paste them into the `TABLES` constant.

### How parity is kept

The module needs regex lookbehind and the `u` flag with `\u{...}` escapes. Every current browser has them (Safari since
16.4).

- **Character classes.** Python's `re` `\w` `\d` `\s`, `str.isalpha`/`isalnum`/`strip()` and
  `unicodedata.combining` are embedded as range tables generated from Python 3.14 / Unicode 16.0, so they do not
  depend on the JS engine's Unicode version. JS `\s` differs from Python on U+001C–001F, U+0085 and U+FEFF. That
  matters because `fts_parts` splits the query before `normalize` removes U+FEFF.
- **Lengths and slicing.** Every `len()` and every slice that can see an astral character counts code points. The
  Cyrillic stemmers use UTF-16 indices, which is safe because their input is all U+0400–04FF.
- **Case and normalisation.** `NFKC`, `NFKD` and `lower()` use the engine. Checked on Node 22.23 (ICU 78, Unicode 17)
  for every code point assigned in Unicode 16: identical. Final sigma, Turkish İ and ß are covered by vectors.

### Known deviations

1. **The engine's Unicode version.** NFKC/NFKD and case mapping come from the JS engine's ICU, not from a table.
   - Older engines (Unicode < 16) may normalise or lower-case characters added after their version differently. This
     was not measured.
   - Node 22.23 (Unicode 17) differs from Python 3.14 on exactly 29 code points that are unassigned in Unicode 16,
     where Python leaves them unchanged: U+A7CE, U+A7D2 and U+A7D4 lower-case to U+A7CF, U+A7D3 and U+A7D5; U+A7F1
     becomes `s` under NFKC; and U+16EA0–U+16EB8 lower-case to U+16EBB–U+16ED3. None of them is in the golden set.
   - `toUpperCase` differs only on U+A7D3/U+A7D5, and is used only to recognise `OR`.
2. **Not tested:** lone surrogates, which a browser text input cannot produce.
3. **Not ported:**
   - `index_stems`: the index is built in Python.
   - Dictionary lookups, `Edits`, `doc_freq`, `find_places`, the gazetteer and entities.

   With no dictionary, `expand` never builds place or term groups, so it never sets `truncated`. `dict_version` is
   always `"none"`, and `dictionary` is always the "not installed" status.

## Compatibility notes

- Python's `sqlite3` must be built with FTS5 (`python -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table t using fts5(a)')"`).
- Changing `textnorm.normalize`, the stemmers or `translit.match_key` changes stored index contents: bump
  `translit.KEY_VERSION` / `index.FTS_VERSION`, rebuild the dictionary and reindex stored text.
- **KEY_VERSION 3** (personal names): `match_key` folds a few very frequent Arabic/Persian given names and the
  Abd- prefix, in Latin and Cyrillic: Mohamed/Muhammad/Mohammed/Мухаммед, Ahmed/Ahmad/Akhmed, Hussein/Husayn/Hossein,
  Youssef/Yusuf/Yousif/Iosif, and Abdel Rahman = Abd al-Rahman = Abdul Rahman = Abdulrahman = Abdurrahman
  (Abdallah = Abdullah = Abd Allah). A non-initial al/el/ul is kept but spelled one way (Mohamed El-Masri =
  Mohammed al-Masri, which stays distinct from Mohamed Masri); a leading article is dropped as before. The folds
  are whole-key patterns (`translit._name_fold`, `translit.join_keys`), not a general vowel fold: over the 322k names
  of a UA+SD `dictionary.db` they add 102 Latin fold pairs (+0.15%; mostly Wadi el X = Wadi al X), where folding
  a/e/i would add +80% and a single vowel class +264%. `latin_key` / `cy_key` are unchanged, so the index's
  romanised tokens are too: no `FTS_VERSION` bump or reindex, but `dictionary.db` must be rebuilt.
  `python scripts/key_report.py dictionary.db` measures any key change against a built file.
- `find_places` tuning (rank thresholds, guards, curated ambiguity list) is precision-first: a mention is a claim in
  the text, not an identification.

## Licence

Not yet chosen; see `NOTICE.md` for the data licences (ODbL / CC BY 4.0) that apply regardless.
