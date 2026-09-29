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

## Compatibility notes

- Python's `sqlite3` must be built with FTS5 (`python -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table t using fts5(a)')"`).
- Changing `textnorm.normalize`, the stemmers or `translit.match_key` changes stored index contents: bump
  `translit.KEY_VERSION` / `index.FTS_VERSION`, rebuild the dictionary and reindex stored text.
- `find_places` tuning (rank thresholds, guards, curated ambiguity list) is precision-first: a mention is a claim in
  the text, not an identification.

## Licence

Not yet chosen; see `NOTICE.md` for the data licences (ODbL / CC BY 4.0) that apply regardless.
