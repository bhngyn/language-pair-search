# Gazetteer / lexicon dictionary

`dictionary.db` (about 50 MB) is a database derived from OpenStreetMap and GeoNames. It is **not committed to this repository**: build it with `python -m language_pair_search.gazetteer_build` (see *Rebuilding*), or copy a built file from the Telegram Investigator project. Anyone who distributes it must offer it under the **ODbL 1.0** (share-alike, attribution required), independent of the code licence. See `NOTICE.md` at the repository root. At runtime it is read-only and nothing is fetched. Rebuild it to change sources or after `translit.KEY_VERSION` changes (`lexicon.dict_status()` reports `key_version_ok: false` when the file is out of date).

The details below (hashes, stats) describe the file this repository's inputs were last built into.

- built_at: `2026-09-29T06:49:56Z`
- version: `d380c0e3918a67c7dd3b0f81cf708ef95706315c6caa2d33e24fad83a533216f` (sha256 over the input files' sha256 + builder version 1.0)
- key_version: `2` (`translit.KEY_VERSION` the keys were computed with; the file's `meta` table records all of these)

## Sources and licences

Coverage: Ukraine (UA) and Sudan (SD), plus a small number of places in RU and TD.

| Source | Files | Licence | Attribution |
|---|---|---|---|
| GeoNames dump and alternateNamesV2 | `UA/UA.txt`, `alt_UA/UA.txt`, `SD/SD.txt`, `alt_SD/SD.txt` (downloaded 2026-09-29) | CC BY 4.0 | GeoNames, CC BY 4.0, https://www.geonames.org |
| Geofabrik OpenStreetMap extracts | `ukraine-260928.osm.pbf`, `sudan-260928.osm.pbf` (2026-09-28) | ODbL 1.0 | © OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright |
| Curated places | `curated/sudan_places.json`, `curated/ukraine_places.json` | project-authored (project licence) | |
| Ambiguous-name deny list | `curated/ambiguous_names.json` | project-authored | |
| Term lexicon | `../lexicon/sudan_lexicon.json`, `../lexicon/ukraine_lexicon.json` | project-authored | |

Input file sha256 hashes: GeoNames `UA/UA.txt` `2db6b3f9b3c149cf…`, `alt_UA` `f7ade55dbacf1c20…`, `SD/SD.txt` `922426afc9b3ac9f…`, `alt_SD` `977e03c216115302…`; OSM `ukraine-260928` `6a4e3140a9de808e…`, `sudan-260928` `9adb2d1fab496b4b…`. Full hashes are in the database's `meta` table.

**Attribution to carry with any export or report that used this data:**

- © OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright
- GeoNames, CC BY 4.0, https://www.geonames.org

The curated places and the lexicon are a search vocabulary, not a source of evidence. **The lexicon contains slurs, derogatory terms and propaganda vocabulary on purpose**, so researchers can find and document that language; such entries are marked in their notes. A match on a place name is a search aid, not an identification of the place.

**Known coverage gaps:** small Sudanese villages often have no Arabic name in OSM or GeoNames. Ukraine is much denser than Sudan. No other countries are covered.

## Counts

- entries: 114969, names: 321912
- SD entries with an Arabic name: 15861
- UA entries with a Russian name: 50874; with a historic name: 5015 (both: 4771)

names by lang: ar 19807, en 94970, latn 56925, other 2438, ru 63294, uk 84478

| country/kind/category | entries |
|---|---|
| -/term/actor | 98 |
| -/term/attack | 24 |
| -/term/humanitarian | 32 |
| -/term/military | 48 |
| -/term/other | 15 |
| -/term/place-type | 34 |
| -/term/slang | 42 |
| -/term/unit | 45 |
| -/term/violation | 54 |
| -/term/weapon | 69 |
| RU/place/city | 4 |
| RU/place/military | 1 |
| RU/place/state | 3 |
| RU/place/town | 5 |
| RU/place/village | 5 |
| SD/place/airport | 87 |
| SD/place/bridge | 265 |
| SD/place/camp | 87 |
| SD/place/city | 72 |
| SD/place/district | 217 |
| SD/place/hamlet | 1672 |
| SD/place/industrial | 126 |
| SD/place/landmark | 3664 |
| SD/place/locality | 1482 |
| SD/place/military | 49 |
| SD/place/mountain | 7907 |
| SD/place/neighbourhood | 383 |
| SD/place/region | 17 |
| SD/place/river | 1644 |
| SD/place/state | 44 |
| SD/place/station | 217 |
| SD/place/suburb | 73 |
| SD/place/town | 446 |
| SD/place/village | 11192 |
| SD/place/wadi | 4288 |
| TD/place/town | 2 |
| UA/place/airport | 616 |
| UA/place/bridge | 5062 |
| UA/place/camp | 2 |
| UA/place/city | 68 |
| UA/place/district | 3609 |
| UA/place/hamlet | 881 |
| UA/place/industrial | 9400 |
| UA/place/landmark | 425 |
| UA/place/locality | 6735 |
| UA/place/military | 1037 |
| UA/place/mountain | 4601 |
| UA/place/neighbourhood | 5503 |
| UA/place/raion | 230 |
| UA/place/region | 31 |
| UA/place/river | 3121 |
| UA/place/state | 43 |
| UA/place/station | 2468 |
| UA/place/suburb | 2313 |
| UA/place/town | 1310 |
| UA/place/village | 33101 |

## How it is built

1. GeoNames (UA, SD) main dump + alternateNamesV2: populated places, ADM1-4, and selected S/H/T/L features.
2. OSM (Geofabrik extracts) filtered with `osmium tags-filter`, parsed from OPL; names split by script, `old_name*` marked historic. Extracted features are cached in `raw/cache/` keyed by the pbf sha256.
3. OSM and GeoNames features merge into one entry when they share a `translit.match_key` (>=4 chars), are in the same feature class, and are within 5 km (15 km cities/pop>100k, 30 km districts/rivers, 100 km states).
4. Curated places merge by key within 15 km (or by key alone when they have no coordinates and one high-rank match), else become new entries. Curated/lexicon names are all `expand=1`.
5. Lexicon entries with the same id across the Sudan/Ukraine files merge into one `term:<id>` entry.

Build stats for the shipped file: curated_merged=325, curated_new=174, osm_dropped_nocoords=241, osm_merged=80324, osm_new=61825, short=884.

## Rebuilding

The build downloads nothing. Put the inputs in `raw/` yourself (about 1.1 GB, git-ignored):

1. `brew install osmium-tool` (only the OSM step needs it; `--no-osm` skips OSM).
2. GeoNames, from https://download.geonames.org/export/dump/: `UA.zip` and `SD.zip`, unzipped to `raw/UA/UA.txt` and `raw/SD/SD.txt`; and `alternatenames/UA.zip` and `alternatenames/SD.zip` (alternateNamesV2), unzipped to `raw/alt_UA/UA.txt` and `raw/alt_SD/SD.txt`.
3. Geofabrik, from https://download.geofabrik.de/: `europe/ukraine-latest.osm.pbf` and `africa/sudan-latest.osm.pbf`, saved in `raw/` as `ukraine-<date>.osm.pbf` and `sudan-<date>.osm.pbf` (file names must match `ukraine-*.osm.pbf` / `sudan-*.osm.pbf`), each with its `.md5` alongside if you want the download verified.
4. `.venv/bin/python -m language_pair_search.gazetteer_build`. Other flags: `--check` (print spot checks on the existing file only), `--out PATH`, `--no-readme`. It writes a temp file and renames it atomically, so a failed build leaves the old file in place. OSM extraction is slow the first time and cached afterwards.

A rebuild also writes `BUILD.md` next to it: the generated build record (input files with SHA-256 hashes, build date, version, counts). `--no-readme` skips it. This README is hand-written and never overwritten.

