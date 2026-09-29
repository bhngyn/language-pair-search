# Third-party notices

This project builds on the following. Their licences apply to those parts.

## Data

**`src/language_pair_search/data/gazetteer/dictionary.db`** is a derivative database. It is built by `src/language_pair_search/gazetteer_build.py` from:

- **OpenStreetMap** data, © OpenStreetMap contributors, available under the
  [Open Database License 1.0 (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/).
  See <https://www.openstreetmap.org/copyright>. The extracts came from Geofabrik (download.geofabrik.de).
  *Share-alike:* anyone who distributes `dictionary.db`, or another database derived from it,
  must offer that database under the ODbL, keep this attribution, and not add technical restrictions.
  The built database is not committed here either; rebuild it from the raw inputs (about 1.1 GB, not in this repository). The download sources are listed in `src/language_pair_search/data/gazetteer/README.md`.
- **GeoNames** gazetteer data (<https://www.geonames.org>), licensed under
  [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).
- **Curated place lists and lexicons** in `src/language_pair_search/data/gazetteer/curated/` and `src/language_pair_search/data/lexicon/`,
  written for this project. They carry the same licence as the project.

The exact input files, their SHA-256 hashes and the build date are recorded in
`src/language_pair_search/data/gazetteer/README.md` and in the database's `meta` table.

**Content note:** the lexicons deliberately include slurs, derogatory terms and propaganda vocabulary used in the
channels this library is built to help find (for example RSF/SAF slurs and Russian terms for Ukrainians). They are
there so investigators can find that language. Each such term is marked in its entry's `notes`.

No Python dependencies are required at runtime (standard library only). Rebuilding the gazetteer's OSM step needs the `osmium` command-line tool (osmium-tool, GPL-3.0; run as a separate program, not bundled).
