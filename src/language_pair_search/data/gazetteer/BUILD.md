# dictionary.db: build record (generated; see README.md for sources, licences and rebuilding)

`dictionary.db` is a **build output** (read-only at runtime; the tool never fetches anything). Rebuild with `python -m language_pair_search.gazetteer_build`.

- built_at: `2026-09-29T08:34:49Z`
- version: `15d4b07d6dff72caf1169b44cfefd0fb04678f6502880f096ae1400c9301429c` (sha256 over the input files' sha256 + builder version 1.0)
- key_version: `2` (translit.KEY_VERSION the keys were computed with)

## Sources and licences

- **GeoNames** `UA/UA.txt` sha256 `2db6b3f9b3c149cf…` (date 2026-09-29) - CC BY 4.0. GeoNames, CC BY 4.0, https://www.geonames.org
- **GeoNames** `alt_UA/UA.txt` sha256 `f7ade55dbacf1c20…` (date 2026-09-29) - CC BY 4.0. GeoNames, CC BY 4.0, https://www.geonames.org
- **Geofabrik OpenStreetMap extract** `ukraine-260928.osm.pbf` sha256 `6a4e3140a9de808e…` (date 20260928) - ODbL 1.0. © OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright
- **GeoNames** `SD/SD.txt` sha256 `922426afc9b3ac9f…` (date 2026-09-29) - CC BY 4.0. GeoNames, CC BY 4.0, https://www.geonames.org
- **GeoNames** `alt_SD/SD.txt` sha256 `977e03c216115302…` (date 2026-09-29) - CC BY 4.0. GeoNames, CC BY 4.0, https://www.geonames.org
- **Geofabrik OpenStreetMap extract** `sudan-260928.osm.pbf` sha256 `9adb2d1fab496b4b…` (date 20260928) - ODbL 1.0. © OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright
- **Curated places** `data/gazetteer/curated/russia_places.json` sha256 `174e572df8251311…` - project-authored. 
- **Curated places** `data/gazetteer/curated/sudan_places.json` sha256 `e7ae9b9201bac25a…` - project-authored. 
- **Curated places** `data/gazetteer/curated/ukraine_places.json` sha256 `4e91fa1237c31eaf…` - project-authored. 
- **Ambiguous-name deny list** `data/gazetteer/curated/ambiguous_names.json` sha256 `9f7af4b2ef1e58a7…` - project-authored. 
- **Term lexicon** `data/lexicon/sudan_lexicon.json` sha256 `c0d1a2eb06605c00…` - project-authored. 
- **Term lexicon** `data/lexicon/ukraine_lexicon.json` sha256 `debddfa9cf9b63c7…` - project-authored. 

Attribution to carry with any export or report using this data:

- © OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright
- GeoNames, CC BY 4.0, https://www.geonames.org

Curated places/lexicon entries are project-authored; the lexicon is a search vocabulary, not a source of evidence.

## Counts

- entries: 115016, names: 322066
- SD entries with an Arabic name: 15861
- UA entries with a Russian name: 50874; with a historic name: 5015 (both: 4771)

names by lang: ar 19807, en 95017, latn 56933, other 2438, ru 63345, uk 84526

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
| RU/place/city | 37 |
| RU/place/military | 1 |
| RU/place/region | 4 |
| RU/place/state | 3 |
| RU/place/town | 14 |
| RU/place/village | 6 |
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

Rebuild: `.venv/bin/python -m language_pair_search.gazetteer_build` (needs `osmium` on PATH for the OSM step; `--no-osm` skips it). The build writes a temp file and renames it atomically.

Build stats: curated_merged=325, curated_new=221, osm_dropped_nocoords=241, osm_merged=80324, osm_new=61825, short=884
