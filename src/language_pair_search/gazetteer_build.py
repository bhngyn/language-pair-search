"""
Gazetteer / lexicon builder: writes src/language_pair_search/data/gazetteer/dictionary.db (+ README.md).

    python -m language_pair_search.gazetteer_build            # build with whatever inputs are present
    python -m language_pair_search.gazetteer_build --no-osm   # GeoNames + curated + lexicon only
    python -m language_pair_search.gazetteer_build --check    # only print the spot checks on the existing db

Inputs (all local, nothing is fetched):
  data/gazetteer/raw/{UA,SD}/*.txt, raw/alt_{UA,SD}/*.txt   GeoNames dump + alternateNamesV2
  data/gazetteer/raw/{sudan,ukraine}-*.osm.pbf (+ .md5)      Geofabrik OSM extracts (osmium CLI)
  data/gazetteer/curated/{sudan,ukraine}_places.json         curated places   (optional)
  data/lexicon/{sudan,ukraine}_lexicon.json                  term lexicon (optional)

Every names.key is
translit.match_key(name). The build is deterministic for the same inputs (except built_at).
"""

import argparse
import collections
import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import translit
from .translit import match_key, script_of

BUILDER_VERSION = "1.0"
EXTRACT_VERSION = "1"          # bump when OSM extraction logic changes (invalidates the cache)

HERE = Path(__file__).resolve().parent
GAZ = HERE / "data" / "gazetteer"
RAW = GAZ / "raw"
CURATED = GAZ / "curated"
LEXDIR = HERE / "data" / "lexicon"
CACHE = RAW / "cache"

OSM_ATTR = "© OpenStreetMap contributors, ODbL 1.0, https://www.openstreetmap.org/copyright"
GN_ATTR = "GeoNames, CC BY 4.0, https://www.geonames.org"

# sizes reported for the 2026-09-28 Geofabrik extracts (used when no .md5 file is present)
EXPECTED_SIZE = {"sudan-260928.osm.pbf": 204324249, "ukraine-260928.osm.pbf": 878554347}

COUNTRIES = {"UA": {"pbf": "ukraine-*.osm.pbf", "gn": "UA"}, "SD": {"pbf": "sudan-*.osm.pbf", "gn": "SD"}}

# ---------------------------------------------------------------- categories
RANK = {"state": 9, "region": 6, "city": 8, "town": 7, "raion": 6, "district": 6, "village": 5,
        "suburb": 4, "camp": 4, "neighbourhood": 3, "hamlet": 3, "locality": 2,
        "airport": 5, "military": 4, "bridge": 4, "station": 4, "industrial": 4, "river": 5,
        "wadi": 4, "mountain": 4, "landmark": 3}
SETTLE = {"city", "town", "village", "hamlet", "suburb", "neighbourhood", "locality", "camp"}
CLASS = {"state": "top", "region": "top", "raion": "district", "district": "district"}
for _c in SETTLE:
    CLASS[_c] = "settle"
CATEGORIES = set(RANK)


def cls_of(cat):
    return CLASS.get(cat, cat)          # other categories are their own class


def radius_km(a_cat, a_pop, b_cat, b_pop):
    ca, cb = cls_of(a_cat), cls_of(b_cat)
    if "top" in (ca, cb):
        return 100.0
    if ca == "district" or cb == "district":
        return 30.0
    if ca in ("river", "wadi") or cb in ("river", "wadi"):
        return 30.0
    if (a_pop or 0) > 100000 or (b_pop or 0) > 100000 or "city" in (a_cat, b_cat):
        return 15.0
    return 5.0


def rank_of(cat, pop):
    r = RANK.get(cat, 2)
    if (pop or 0) > 100000:
        r += 1
    return r


# ---------------------------------------------------------------- names
_APOSTROPHES = re.compile("[’ʼʻ`´]")
_AR_CH = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_CY_CH = re.compile("[Ѐ-ӿ]")
_LA_CH = re.compile("[A-Za-zÀ-ɏḀ-ỿ]")
_UK_ONLY = re.compile("[іїєґІЇЄҐ]")
_RU_ONLY = re.compile("[ыэъёЫЭЪЁ]")
_STRIP = " \t-/|()[]{}«»\"',.:;–—_*"


def clean(name):
    name = name.strip()
    if _AR_CH.search(name) and re.search("[ﭐ-﷿ﹰ-﻿]", name):
        name = unicodedata.normalize("NFKC", name)
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def char_script(ch):
    if _AR_CH.match(ch):
        return "ar"
    if _CY_CH.match(ch):
        return "cy"
    if _LA_CH.match(ch):
        return "la"
    return ""


def split_scripts(value):
    """'El Fasher الفاشر' -> ['El Fasher', 'الفاشر'] ; single-script values pass through."""
    scripts = {char_script(c) for c in value} - {""}
    if len(scripts) < 2:
        return [value]
    runs, cur, cur_s = [], "", ""
    for ch in value:
        s = char_script(ch)
        if s and cur_s and s != cur_s:
            runs.append((cur_s, cur))
            cur = ""
        if s:
            cur_s = s
        cur += ch
    runs.append((cur_s, cur))
    return [r.strip(_STRIP) for _, r in runs if r.strip(_STRIP)]


def cy_lang(name, country, default):
    if _UK_ONLY.search(name):
        return "uk"
    if _RU_ONLY.search(name):
        return "ru"
    return default


def junk(name):
    if len(name) > 120 or not any(c.isalpha() for c in name):
        return True
    letters = sum(c.isalpha() for c in name)
    return letters < 2


class Ent:
    __slots__ = ("country", "cat", "label", "label_pri", "admin1", "lat", "lon", "coord_pri", "pop",
                 "sources", "names", "notes", "kind", "id", "keys4", "gn_admin1")

    def __init__(self, country, cat, label="", lat=None, lon=None, pop=0, kind="place"):
        self.country, self.cat, self.label, self.label_pri = country, cat, label, 0
        self.lat, self.lon, self.coord_pri, self.pop = lat, lon, 0, pop or 0
        self.admin1 = None
        self.gn_admin1 = None
        self.sources, self.notes, self.kind, self.id = [], "", kind, None
        self.names = {}          # (key, lang) -> [name, historic, expand, source]
        self.keys4 = set()

    def add_name(self, name, lang, historic=0, expand=1, source="gn", stats=None):
        name = clean(name)
        if not name:
            return False
        if junk(name):
            if stats is not None:
                stats["junk"][name[:30]] += 1
            return False
        key = match_key(name)
        if len(key) < 3:
            if stats is not None:
                stats["short"] += 1
            return False
        k = (key, lang)
        cur = self.names.get(k)
        if cur is None:
            self.names[k] = [name, historic, expand, source]
        else:
            if expand and not cur[2]:
                cur[2] = 1
                cur[3] = source
            if not historic:
                cur[1] = 0
        if len(key) >= 4:
            self.keys4.add(key)
        return True

    def sort_key(self):
        return (self.country or "", -rank_of(self.cat, self.pop), self.label.lower(), self.lat or 0)


def dist_km(la1, lo1, la2, lo2):
    dy = (la1 - la2) * 111.2
    dx = (lo1 - lo2) * 111.32 * math.cos(math.radians((la1 + la2) / 2))
    return math.hypot(dx, dy)


# ---------------------------------------------------------------- input hashing
def file_hashes(path):
    """(md5, sha256), cached by size+mtime in raw/cache/hashes.json."""
    path = Path(path)
    st = path.stat()
    CACHE.mkdir(parents=True, exist_ok=True)
    hp = CACHE / "hashes.json"
    try:
        H = json.loads(hp.read_text())
    except Exception:
        H = {}
    ent = H.get(str(path))
    if ent and ent[0] == st.st_size and ent[1] == st.st_mtime:
        return ent[2], ent[3]
    m, s = hashlib.md5(), hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            m.update(b)
            s.update(b)
    H[str(path)] = [st.st_size, st.st_mtime, m.hexdigest(), s.hexdigest()]
    hp.write_text(json.dumps(H))
    return m.hexdigest(), s.hexdigest()


def sha_only(path):
    return file_hashes(path)[1]


# ---------------------------------------------------------------- GeoNames
GN_SKIP_LANG = {"link", "wkdt", "post", "iata", "icao", "faac", "unlc", "abbr", "tpfx", "fr_1793", "lauc",
                "nuts", "geo", "wkdt", "unlc"}


def gn_category(fc, code, pop, cc, has_alt, name):
    """-> category or None (skip)."""
    if fc == "P":
        if code in ("PPLC", "PPLA"):
            return "city"
        if code == "PPLX":
            return "suburb"
        if code in ("PPLQ", "PPLH", "PPLW", "PPLCH", "PPLR"):
            return "locality"
        if code in ("PPLL", "PPLF", "PPLS"):
            return "hamlet"
        if code in ("PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPL", "PPLG"):
            if pop >= 100000:
                return "city"
            if pop >= 15000:
                return "town"
            if code == "PPLA2" and pop >= 3000:
                return "town"
            return "village"
        return "village"
    if fc == "A":
        if code == "ADM1":
            return "state"
        if code == "ADM2":
            return "raion" if cc == "UA" else "district"
        if code in ("ADM3", "ADM4"):
            return "district"
        if code == "PCLI":
            return "region"
        return None
    if fc == "S":
        if code in ("AIRP", "AIRF", "AIRB"):
            return "airport"
        if code in ("MILB", "INSM"):
            return "military"
        if code in ("CMPRF", "CMP"):
            return "camp"
        if code == "BDG":
            return "bridge"
        if code == "RSTN":
            return "station"
        if code == "DAM":
            return "landmark"
        return None
    if fc == "H":
        if code.startswith("WAD"):
            return "wadi"
        if code == "STM" and len(name) >= 5 and has_alt:
            return "river"
        return None
    if fc == "T":
        if code in ("MT", "MTS") and has_alt:
            return "mountain"
        return None
    if fc == "L":
        if code == "RGN":
            return "region"
        if code == "AREA":
            return "locality"
    return None


def load_geonames(cc, stats):
    main = RAW / cc / f"{cc}.txt"
    alt = RAW / f"alt_{cc}" / f"{cc}.txt"
    rows = {}
    admin1_names = {}
    with open(main, encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 15:
                continue
            gid, name, ascii_ = p[0], p[1], p[2]
            fc, code = p[6], p[7]
            if code == "ADM1":
                admin1_names[p[10]] = ascii_ or name
            rows[gid] = (p, fc, code)
    alts = collections.defaultdict(list)
    with open(alt, encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 4 or p[1] not in rows:
                continue
            alts[p[1]].append(p)
    ents = []
    for gid, (p, fc, code) in rows.items():
        name, ascii_ = p[1], p[2]
        pop = int(p[14] or 0)
        al = alts.get(gid, [])
        has_alt = any(a[2] in ("ar", "ru", "uk") for a in al)
        cat = gn_category(fc, code, pop, cc, has_alt, ascii_ or name)
        if not cat:
            continue
        e = Ent(cc, cat, lat=float(p[4]), lon=float(p[5]), pop=pop)
        e.coord_pri = 1
        e.sources.append("gn:" + gid)
        e.gn_admin1 = None if cat in ("state", "region") else admin1_names.get(p[10])
        e.admin1 = e.gn_admin1
        en_pref, en_any = None, None
        en_names = set()
        for a in al:
            lang = a[2]
            nm = a[3]
            if not nm or lang in GN_SKIP_LANG or "_" in lang or any(ch.isdigit() for ch in lang):
                continue
            hist = 1 if len(a) > 7 and a[7] == "1" else 0
            sc = script_of(nm)
            if lang == "en" and sc == "la":
                e.add_name(nm, "en", hist, 1, "gn", stats)
                en_names.add(nm)
                if len(a) > 4 and a[4] == "1" and not hist and not en_pref:
                    en_pref = nm
                elif not hist and not en_any:
                    en_any = nm
            elif lang == "ar" and sc == "ar":
                e.add_name(nm, "ar", hist, 1, "gn", stats)
            elif lang in ("ru", "uk") and sc == "cy":
                e.add_name(nm, lang, hist, 1, "gn", stats)
            elif lang == "" and sc == "cy":
                e.add_name(nm, cy_lang(nm, cc, "uk" if cc == "UA" else "ru"), hist, 1, "gn", stats)
            elif lang == "" and sc == "ar":
                e.add_name(nm, "ar", hist, 1, "gn", stats)
            elif sc == "la":
                e.add_name(nm, "latn", hist, 0, "gn", stats)        # other Latin: input matching only
        lab = en_pref or en_any or ascii_ or name
        e.label = lab
        e.label_pri = 1
        # main name + asciiname: 'latn' expand 0 (the label's own name is promoted to 'en' below)
        for nm in (name, ascii_):
            if nm and nm not in en_names and script_of(nm) == "la":
                e.add_name(nm, "latn", 0, 0, "gn", stats)
        if not en_names:
            e.add_name(lab, "en", 0, 1, "gn", stats)
        ents.append(e)
    return ents


# ---------------------------------------------------------------- OSM
def _run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed: {r.stderr[:500]}")
    return r


_OPL_ESC = re.compile(r"%([0-9a-fA-F]+)%")


def opl_unescape(s):
    return _OPL_ESC.sub(lambda m: chr(int(m.group(1), 16)), s) if "%" in s else s


def opl_tags(field):
    out = {}
    if not field:
        return out
    for kv in field.split(","):
        k, _, v = kv.partition("=")
        out[opl_unescape(k)] = opl_unescape(v)
    return out


KEEP_TAG = re.compile(r"^(name(:[a-z]{2,3})?|int_name|alt_name(:[a-z]{2,3})?|old_name(:[a-z]{2,3})?|"
                      r"official_name(:[a-z]{2,3})?|loc_name(:[a-z]{2,3})?|short_name(:[a-z]{2,3})?|"
                      r"place|boundary|admin_level|aeroway|military|landuse|amenity|railway|man_made|bridge|"
                      r"waterway|natural|population|wikidata|refugee|tourism|station)$")
NAMEISH = re.compile(r"^(name|int_name|alt_name|old_name|official_name|loc_name|short_name)(:[a-z]{2,3})?$")

PLACE_MAP = {"city": "city", "town": "town", "village": "village", "hamlet": "hamlet",
             "isolated_dwelling": "hamlet", "farm": "hamlet", "suburb": "suburb", "borough": "suburb",
             "quarter": "neighbourhood", "neighbourhood": "neighbourhood", "city_block": "neighbourhood",
             "locality": "locality", "island": "locality", "islet": "locality", "archipelago": "locality",
             "state": "state", "province": "state", "region": "region", "county": "district",
             "district": "district", "municipality": "district"}


def osm_category(t, country):
    """OSM tag dict -> category or None."""
    pl = t.get("place")
    if pl:
        c = PLACE_MAP.get(pl)
        if c:
            return c
    if t.get("amenity") == "refugee_site":
        return "camp"
    if t.get("aeroway") == "aerodrome":
        return "airport"
    if t.get("military") or t.get("landuse") == "military":
        return "military"
    if t.get("railway") == "station":
        return "station"
    if t.get("landuse") == "industrial" or t.get("man_made") == "works":
        return "industrial"
    ww = t.get("waterway")
    if ww:
        if ww == "wadi":
            return "wadi"
        if ww in ("river", "canal") or (country == "SD" and ww not in ("ditch", "drain", "weir", "lock_gate")):
            return "river"
        if ww == "dam":
            return "landmark"
    nat = t.get("natural")
    if nat in ("peak", "mountain_range"):
        return "mountain"
    if nat == "valley":
        return "landmark"
    if t.get("man_made") == "bridge" or (t.get("bridge") and t.get("bridge") != "no"):
        return "bridge"
    if t.get("boundary") == "administrative":
        try:
            lvl = int(t.get("admin_level", "0"))
        except ValueError:
            return None
        if lvl == 4:
            return "state"
        if lvl in (5, 6):
            return "raion" if country == "UA" else "district"
        if lvl in (7, 8):
            return "locality"
    return None


OSM_EXPR = ["nwr/place", "nwr/aeroway=aerodrome", "nwr/military", "nwr/landuse=military",
            "nwr/amenity=refugee_site", "nwr/railway=station", "w/man_made=bridge", "w/bridge",
            "nwr/man_made=works", "nwr/landuse=industrial", "w/waterway", "n/waterway=dam",
            "nwr/natural=peak", "nwr/natural=mountain_range", "nwr/natural=valley",
            "r/boundary=administrative"]


def extract_osm(pbf, cc, sha):
    """osmium-filter the pbf and return a list of {id, lat, lon, cp, tags}; cached by pbf sha."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"osm-{cc}-{sha[:16]}-v{EXTRACT_VERSION}.jsonl.gz"
    if cache.exists():
        with gzip.open(cache, "rt", encoding="utf-8") as f:
            return [json.loads(l) for l in f]
    t0 = time.time()
    cand = CACHE / f"cand-{cc}-{sha[:16]}.osm.pbf"
    if not cand.exists():
        tmp = CACHE / f"cand-{cc}.tmp.osm.pbf"
        _run(["osmium", "tags-filter", "-R", "--overwrite", "-o", str(tmp), str(pbf)] + OSM_EXPR)
        os.replace(tmp, cand)
    print(f"  [{cc}] osmium tags-filter {time.time()-t0:.0f}s", flush=True)

    feats = []            # dict(id, ot, tags, lat, lon, cp)
    want_ways, want_rels, want_nodes = {}, {}, set()
    proc = subprocess.Popen(["osmium", "cat", str(cand), "-f", "opl,add_metadata=false", "-o", "-"],
                            stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1 << 20)
    for line in proc.stdout:
        p = line.rstrip("\n").split(" ")
        head = p[0]
        ot, oid = head[0], head[1:]
        fields = {x[0]: x[1:] for x in p[1:] if x}
        allt = opl_tags(fields.get("T", ""))
        if not any(NAMEISH.match(k) for k in allt):
            continue
        cat = osm_category(allt, cc)
        if not cat:
            continue
        if allt.get("bridge") == "no":
            continue
        tags = {k: v for k, v in allt.items() if KEEP_TAG.match(k)}
        rec = {"id": head, "tags": tags, "lat": None, "lon": None, "cp": 0}
        if ot == "n":
            rec["lat"], rec["lon"], rec["cp"] = float(fields["y"]), float(fields["x"]), 3
            feats.append(rec)
        elif ot == "w":
            want_ways[oid] = rec
            feats.append(rec)
        elif ot == "r":
            if tags.get("boundary") == "administrative" and not tags.get("place"):
                # geometry too heavy: use admin_centre / label member node
                for m in fields.get("M", "").split(","):
                    mm = m.split("@")
                    if len(mm) == 2 and mm[0][0] == "n" and mm[1] in ("admin_centre", "label"):
                        rec.setdefault("_nodes", []).append(mm[0][1:])
                        want_nodes.add(mm[0][1:])
                if tags.get("admin_level", "") not in ("4", "5", "6", "7", "8"):
                    continue
                if cat == "locality" and "_nodes" not in rec:
                    continue
                feats.append(rec)
            else:
                want_rels[oid] = rec
                feats.append(rec)
    proc.wait()
    print(f"  [{cc}] candidates {len(feats)} (ways {len(want_ways)}, rels {len(want_rels)}) {time.time()-t0:.0f}s",
          flush=True)

    # coordinates for ways / relations / admin_centre nodes via getid -r
    ids = [f"w{i}" for i in want_ways] + [f"r{i}" for i in want_rels] + [f"n{i}" for i in want_nodes]
    if ids:
        idf = CACHE / f"ids-{cc}.txt"
        idf.write_text("\n".join(ids) + "\n")
        outf = CACHE / f"sub-{cc}.opl"
        r = subprocess.run(["osmium", "getid", "-r", "--overwrite", "-i", str(idf), "-f", "opl,add_metadata=false",
                            "-o", str(outf), str(pbf)], capture_output=True, text=True)
        if r.returncode not in (0, 1) or not outf.exists():        # rc 1: some requested ids not in the extract
            raise RuntimeError("osmium getid failed: " + r.stderr[:500])
        print(f"  [{cc}] osmium getid {time.time()-t0:.0f}s", flush=True)
        nodes, ways, rels = {}, {}, {}
        with open(outf, encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split(" ")
                h = p[0]
                if h[0] == "n":
                    x = y = None
                    for tok in p[1:]:
                        if tok[:1] == "x":
                            x = tok[1:]
                        elif tok[:1] == "y":
                            y = tok[1:]
                    if x and y:
                        nodes[h[1:]] = (float(y), float(x))
                elif h[0] == "w":
                    for tok in p[1:]:
                        if tok[:1] == "N":
                            ways[h[1:]] = tok[1:].split(",") if len(tok) > 1 else []
                elif h[0] == "r":
                    for tok in p[1:]:
                        if tok[:1] == "M":
                            rels[h[1:]] = [m.split("@")[0] for m in tok[1:].split(",") if m]

        def centre(nids):
            pts = [nodes[n[1:] if n[:1] == "n" else n] for n in nids if (n[1:] if n[:1] == "n" else n) in nodes]
            if not pts:
                return None
            return sum(a for a, _ in pts) / len(pts), sum(b for _, b in pts) / len(pts)

        for i, rec in want_ways.items():
            c = centre(ways.get(i, []))
            if c:
                rec["lat"], rec["lon"], rec["cp"] = c[0], c[1], 1
        for i, rec in want_rels.items():
            nids = []
            for m in rels.get(i, []):
                if m[:1] == "w":
                    nids += ways.get(m[1:], [])
                elif m[:1] == "n":
                    nids.append(m[1:])
            c = centre(nids)
            if c:
                rec["lat"], rec["lon"], rec["cp"] = c[0], c[1], 1
        for rec in feats:
            if rec["id"][0] == "r" and "_nodes" in rec:
                c = centre(rec["_nodes"])
                if c:
                    rec["lat"], rec["lon"], rec["cp"] = c[0], c[1], 2
        for f_ in (idf, outf):
            try:
                f_.unlink()
            except OSError:
                pass
    for rec in feats:
        rec.pop("_nodes", None)
    tmp = cache.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in feats:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, cache)
    print(f"  [{cc}] extracted {len(feats)} features in {time.time()-t0:.0f}s", flush=True)
    return feats


def osm_names(tags, cc):
    """-> [(name, lang, historic, expand)] from an OSM tag dict."""
    out = []
    for k, v in tags.items():
        m = NAMEISH.match(k)
        if not m:
            continue
        base, lg = m.group(1), (m.group(2) or "")[1:]
        hist = 1 if base == "old_name" else 0
        for part in v.split(";"):
            for val in split_scripts(part.strip()):
                val = clean(val)
                if not val:
                    continue
                sc = script_of(val)
                if sc == "ar":
                    lang, exp = ("ar", 1) if lg in ("", "ar") else ("other", 0)
                elif sc == "cy":
                    if lg in ("ru", "uk"):
                        lang, exp = lg, 1
                    elif lg == "":
                        if cc == "SD":
                            lang, exp = "ru", 1
                        elif base == "old_name":
                            lang, exp = cy_lang(val, cc, "ru"), 1
                        else:
                            lang, exp = cy_lang(val, cc, "uk"), 1
                    else:
                        continue                     # Belarusian, Bulgarian, ... Cyrillic: not kept
                elif sc == "la":
                    if lg == "en" or base == "int_name":
                        lang, exp = "en", 1
                    elif lg == "" and base == "name" and cc == "SD":
                        lang, exp = "en", 1
                    else:
                        lang, exp = "latn", 0
                else:
                    continue
                out.append((val, lang, hist, exp))
    return out


def osm_entry(rec, cc, stats):
    t = rec["tags"]
    cat = osm_category(t, cc)
    if not cat:
        return None
    try:
        pop = int(re.sub(r"\D", "", t.get("population", "")) or 0)
    except ValueError:
        pop = 0
    e = Ent(cc, cat, lat=rec["lat"], lon=rec["lon"], pop=pop)
    e.coord_pri = rec["cp"] + 1 if rec["lat"] is not None else 0
    e.sources.append("osm:" + {"n": "node", "w": "way", "r": "relation"}[rec["id"][0]] + "/" + rec["id"][1:])
    for nm, lang, hist, exp in osm_names(t, cc):
        e.add_name(nm, lang, hist, exp, "osm", stats)
    if not e.names:
        return None
    # label: name:en > int_name > any en > latn > any non-historic
    lab = None
    for k in ("name:en", "int_name"):
        if t.get(k) and script_of(t[k]) == "la":
            lab = clean(split_scripts(t[k].split(";")[0])[0])
            break
    if not lab:
        for (key, lang), (nm, h, ex, s) in e.names.items():
            if lang == "en" and not h:
                lab = nm
                break
    if not lab:
        for pref in ("latn", "uk", "ar", "ru"):
            for (key, lang), (nm, h, ex, s) in e.names.items():
                if lang == pref and not h:
                    lab = nm
                    break
            if lab:
                break
    e.label = lab or next(iter(e.names.values()))[0]
    e.label_pri = 2 if t.get("name:en") else 1
    return e


# ---------------------------------------------------------------- merging
class Index:
    def __init__(self):
        self.by_key = collections.defaultdict(list)      # (country, key) -> [Ent]

    def add(self, e):
        for k in e.keys4:
            self.by_key[(e.country, k)].append(e)

    def candidates(self, e):
        seen, out = set(), []
        for k in e.keys4:
            for c in self.by_key.get((e.country, k), ()):
                if id(c) not in seen:
                    seen.add(id(c))
                    out.append(c)
        return out


def compatible(a_cat, b_cat):
    ca, cb = cls_of(a_cat), cls_of(b_cat)
    if ca == cb:
        return True
    return {ca, cb} <= {"settle", "camp"}


def merge_into(t, e):
    """merge Ent e into t."""
    for (key, lang), v in e.names.items():
        cur = t.names.get((key, lang))
        if cur is None:
            t.names[(key, lang)] = list(v)
        else:
            if v[2] and not cur[2]:
                cur[2] = 1
                cur[3] = v[3]
            if not v[1]:
                cur[1] = 0
    t.keys4 |= e.keys4
    t.sources += e.sources
    if e.label_pri > t.label_pri and e.label:
        t.label, t.label_pri = e.label, e.label_pri
    if e.lat is not None and (t.lat is None or e.coord_pri > t.coord_pri):
        t.lat, t.lon, t.coord_pri = e.lat, e.lon, e.coord_pri
    t.pop = max(t.pop, e.pop)
    if e.notes and not t.notes:
        t.notes = e.notes
    if e.admin1 and not t.admin1:
        t.admin1 = e.admin1
    # category: highest rank wins, but 'camp' beats the small settlement classes
    if e.cat != t.cat:
        cats = {t.cat, e.cat}
        if "camp" in cats and cats <= (SETTLE | {"camp"}) and not (cats & {"city", "town"}):
            t.cat = "camp"
        elif RANK.get(e.cat, 0) > RANK.get(t.cat, 0):
            t.cat = e.cat


def find_target(idx, e, override_radius=None):
    best, bd = None, 1e9
    coordless = []
    for c in idx.candidates(e):
        if not compatible(c.cat, e.cat):
            continue
        if e.lat is None or c.lat is None:
            coordless.append(c)
            continue
        d = dist_km(e.lat, e.lon, c.lat, c.lon)
        r = override_radius or radius_km(e.cat, e.pop, c.cat, c.pop)
        if d <= r and d < bd:
            best, bd = c, d
    if best is None and e.lat is None:
        hi = [c for c in coordless if RANK.get(c.cat, 0) >= 5] or coordless
        if len({id(c) for c in hi}) == 1:
            return hi[0]
    return best


def merge_osm(gn_ents, osm_ents, stats):
    idx = Index()
    for e in gn_ents:
        idx.add(e)
    out = list(gn_ents)
    order = sorted(osm_ents, key=lambda e: (-rank_of(e.cat, e.pop), e.lat is None))
    for e in order:
        t = find_target(idx, e)
        if t is not None:
            merge_into(t, e)
            idx.add(t)
            stats["osm_merged"] += 1
        else:
            if e.lat is None and cls_of(e.cat) not in ("top", "district"):
                stats["osm_dropped_nocoords"] += 1
                continue
            out.append(e)
            idx.add(e)
            stats["osm_new"] += 1
    return out, idx


# ---------------------------------------------------------------- curated + lexicon
def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as ex:
        print(f"  WARNING: cannot read {path}: {ex}", flush=True)
        return []


def apply_curated(ents, idx, stats):
    files = sorted(CURATED.glob("*_places.json")) if CURATED.is_dir() else []
    used = []
    for fp in files:
        data = load_json(fp)
        used.append(fp)
        for r in data:
            cc = r.get("country") or ("UA" if "ukraine" in fp.name else "SD")
            cat = r.get("type") or "locality"
            if cat not in CATEGORIES:
                cat = {"town": "town", "oblast": "state", "province": "state", "governorate": "state"}.get(cat, "landmark")
            e = Ent(cc, cat, lat=r.get("lat"), lon=r.get("lon"), pop=int(r.get("population") or 0))
            e.coord_pri = 5 if e.lat is not None else 0
            e.label, e.label_pri = (r.get("en") or "").strip(), 3
            e.admin1 = r.get("admin1") or None
            e.sources.append("curated")
            notes = (r.get("notes") or "").strip()
            conf = r.get("confidence")
            if conf and conf != "high":
                notes = (notes + f" [confidence: {conf}]").strip()
            e.notes = notes
            if e.label:
                e.add_name(e.label, "en", 0, 1, "curated", stats)
            for lang, key in (("latn", "latin"), ("ar", "ar"), ("ru", "ru"), ("uk", "uk"), ("en", "en_alt")):
                for nm in r.get(key) or []:
                    if isinstance(nm, str):
                        e.add_name(nm, lang, 0, 1, "curated", stats)
            for nm in r.get("historic") or []:
                if isinstance(nm, str):
                    sc = script_of(nm)
                    lang = "ar" if sc == "ar" else ("latn" if sc == "la" else cy_lang(nm, cc, "ru"))
                    e.add_name(nm, lang, 1, 1, "curated", stats)
            if not e.names:
                continue
            if not e.label:
                e.label = next(iter(e.names.values()))[0]
            t = find_target(idx, e, override_radius=15.0) if e.keys4 else None
            if t is not None:
                merge_into(t, e)
                for (key, lang), v in e.names.items():        # curated names are always expand=1
                    t.names[(key, lang)][2] = 1
                    t.names[(key, lang)][3] = "curated"
                if r.get("type") and cat in CATEGORIES and RANK.get(cat, 0) >= RANK.get(t.cat, 0):
                    t.cat = cat
                if e.admin1:
                    t.admin1 = e.admin1
                idx.add(t)
                stats["curated_merged"] += 1
            else:
                ents.append(e)
                idx.add(e)
                stats["curated_new"] += 1
    return used


def load_lexicon(stats):
    files = sorted(LEXDIR.glob("*_lexicon.json")) if LEXDIR.is_dir() else []
    terms = {}
    for fp in files:
        for r in load_json(fp):
            tid = r.get("id")
            if not tid:
                continue
            e = terms.get(tid)
            if e is None:
                e = Ent(None, r.get("category") or "term", label=r.get("label") or tid, kind="term")
                e.id = "term:" + tid
                e.sources.append("lexicon")
                terms[tid] = e
            if r.get("notes") and not e.notes:
                e.notes = r["notes"]
            for lang in ("en", "ar", "ru", "uk"):
                for nm in r.get(lang) or []:
                    if isinstance(nm, str):
                        e.add_name(nm, lang, 0, 1, "lexicon", stats)
    return list(terms.values()), files


# ---------------------------------------------------------------- admin1 for OSM-only entries
def fill_admin1(ents):
    grid = collections.defaultdict(list)
    for e in ents:
        if e.gn_admin1 and e.lat is not None:
            grid[(e.country, int(e.lat * 2), int(e.lon * 2))].append(e)
    for e in ents:
        if e.kind != "place" or e.admin1 or e.lat is None or e.cat in ("state", "region"):
            continue
        best, bd = None, 60.0
        gi, gj = int(e.lat * 2), int(e.lon * 2)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for c in grid.get((e.country, gi + di, gj + dj), ()):
                    d = dist_km(e.lat, e.lon, c.lat, c.lon)
                    if d < bd:
                        best, bd = c, d
        if best:
            e.admin1 = best.gn_admin1


# ---------------------------------------------------------------- output
SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE entries(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, country TEXT, category TEXT, label TEXT NOT NULL,
  admin1 TEXT, lat REAL, lon REAL, population INTEGER, rank INTEGER NOT NULL DEFAULT 0,
  sources TEXT, notes TEXT);
CREATE TABLE names(
  entry_id TEXT NOT NULL, name TEXT NOT NULL, lang TEXT NOT NULL, historic INTEGER NOT NULL DEFAULT 0,
  expand INTEGER NOT NULL DEFAULT 1, source TEXT, key TEXT NOT NULL);
"""


DENY = set()             # (casefolded name, lang) from curated/ambiguous_names.json
LEX_KEYS = set()         # single-token keys of lexicon names
SUBAREA_WORDS = {"حارة", "الحارة", "حي", "الحي", "مربع", "المربع", "block", "district", "мкр", "микрорайон",
                 "мікрорайон", "район", "квартал"}
DEMOTE = collections.Counter()
DEMOTE_SAMPLES = collections.defaultdict(list)


def load_deny():
    fp = CURATED / "ambiguous_names.json"
    DENY.clear()
    if fp.exists():
        for r in load_json(fp):
            if r.get("name"):
                DENY.add((clean(r["name"]).casefold(), r.get("lang") or "*"))
    return fp if fp.exists() else None


def _ntok(name):
    return len(name.split())


def demote_reason(e, name, lang, key, src, others):
    if src in ("curated", "lexicon") and False:
        pass
    n = clean(name).casefold()
    if (n, lang) in DENY or (n, "*") in DENY:
        return "deny_list"
    if " " not in key and key in LEX_KEYS:
        return "equals_lexicon_term"
    if src in ("curated", "lexicon"):
        return None
    if any(ch.isdigit() for ch in name):
        return "digits"
    if _ntok(name) > 4:
        return "over_4_tokens"
    if e.cat in ("city", "town") and lang in ("ar", "en", "ru", "uk", "latn"):
        toks = set(re.split(r"[\s\-]+", name.casefold()))
        if toks & SUBAREA_WORDS and not any(k2 and (k2 in key or key in k2) for k2 in others):
            return "sub_area_word"
    return None


def finalize_names(e):
    """demote ambiguous names to expand=0; then drop expand=0 names whose key already exists as expand=1."""
    if e.kind == "place":
        for (k, lang), v in e.names.items():
            if not v[2]:
                continue
            others = [k2 for (k2, l2) in e.names if k2 != k]
            r = demote_reason(e, v[0], lang, k, v[3], others)
            if r:
                v[2] = 0
                DEMOTE[r] += 1
                if len(DEMOTE_SAMPLES[r]) < 15:
                    DEMOTE_SAMPLES[r].append(f"{v[0]} [{lang}] in {e.label} ({e.country} {e.cat})")
    exp_keys = {k for (k, lang), v in e.names.items() if v[2]}
    out = []
    for (k, lang), v in e.names.items():
        if not v[2] and k in exp_keys:
            continue
        out.append((v[0], lang, v[1], v[2], v[3], k))
    return out


def write_db(path, places, terms, meta):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix="dictionary-", suffix=".db.tmp", dir=d)
    os.close(fd)
    os.unlink(tmp)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    ne = nn = 0
    langs = collections.Counter()
    by = collections.Counter()
    sd_ar = ua_ru = ua_hist = ua_ru_hist = 0
    for i, e in enumerate(sorted(places, key=lambda e: e.sort_key()), 1):
        e.id = f"place:{i}"
    for e in places + terms:
        pop = e.pop or None
        rank = rank_of(e.cat, e.pop) if e.kind == "place" else 0
        if e.kind == "place" and e.cat in ("region",) and e.label in ("Ukraine", "Sudan"):
            rank = 9
        rows = finalize_names(e)
        if not rows:
            continue
        con.execute("INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (e.id, e.kind, e.country, e.cat, e.label, e.admin1,
                     None if e.lat is None else round(e.lat, 5), None if e.lon is None else round(e.lon, 5),
                     pop, rank, json.dumps(e.sources[:12]), e.notes or None))
        con.executemany("INSERT INTO names VALUES(?,?,?,?,?,?,?)",
                        [(e.id, n, lg, h, ex, src, k) for (n, lg, h, ex, src, k) in rows])
        ne += 1
        nn += len(rows)
        by[(e.country or "-", e.kind, e.cat)] += 1
        ls = {r[1] for r in rows}
        for r in rows:
            langs[r[1]] += 1
        if e.country == "SD" and "ar" in ls:
            sd_ar += 1
        if e.country == "UA":
            if "ru" in ls:
                ua_ru += 1
            if any(r[2] for r in rows):
                ua_hist += 1
            if "ru" in ls and any(r[2] for r in rows):
                ua_ru_hist += 1
    con.execute("CREATE INDEX names_key ON names(key)")
    con.execute("CREATE INDEX names_entry ON names(entry_id)")
    counts = {
        "entries": ne, "names": nn,
        "entries_by_country_kind_category": {f"{c}/{k}/{cat}": n for (c, k, cat), n in sorted(by.items())},
        "names_by_lang": dict(sorted(langs.items())),
        "demoted_expand0": dict(DEMOTE),
        "sd_entries_with_arabic_name": sd_ar,
        "ua_entries_with_ru_name": ua_ru,
        "ua_entries_with_historic_name": ua_hist,
        "ua_entries_with_ru_and_historic_name": ua_ru_hist,
    }
    meta = dict(meta)
    meta["counts"] = counts
    for k, v in meta.items():
        con.execute("INSERT INTO meta VALUES(?,?)", (k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)))
    con.commit()
    con.execute("VACUUM")
    con.close()
    os.replace(tmp, path)
    return counts


def write_readme(path, meta, counts, args_note):
    src = meta["sources"]
    L = ["# dictionary.db: build record (generated; see README.md for sources, licences and rebuilding)", "",
         "`dictionary.db` is a **build output** (read-only at runtime; the tool never fetches anything). "
         "Rebuild with `python -m language_pair_search.gazetteer_build`.", "",
         f"- built_at: `{meta['built_at']}`", f"- version: `{meta['version']}` (sha256 over the input files' sha256 + builder version {BUILDER_VERSION})",
         f"- key_version: `{meta['key_version']}` (translit.KEY_VERSION the keys were computed with)", "",
         "## Sources and licences", ""]
    for s in src:
        L.append(f"- **{s['name']}** `{s['file']}` sha256 `{s['sha256'][:16]}…`"
                 + (f" (date {s['date']})" if s.get("date") else "") + f" - {s['license']}. {s['attribution']}")
    L += ["", "Attribution to carry with any export or report using this data:", "",
          f"- {OSM_ATTR}", f"- {GN_ATTR}", "",
          "Curated places/lexicon entries are project-authored; the lexicon is a search vocabulary, not a source of evidence.", "",
          "## Counts", "", f"- entries: {counts['entries']}, names: {counts['names']}",
          f"- SD entries with an Arabic name: {counts['sd_entries_with_arabic_name']}",
          f"- UA entries with a Russian name: {counts['ua_entries_with_ru_name']}; with a historic name: "
          f"{counts['ua_entries_with_historic_name']} (both: {counts['ua_entries_with_ru_and_historic_name']})",
          "", "names by lang: " + ", ".join(f"{k} {v}" for k, v in counts["names_by_lang"].items()), "",
          "| country/kind/category | entries |", "|---|---|"]
    for k, v in counts["entries_by_country_kind_category"].items():
        L.append(f"| {k} | {v} |")
    L += ["", "## How it is built", "",
          "1. GeoNames (UA, SD) main dump + alternateNamesV2: populated places, ADM1-4, and selected S/H/T/L features.",
          "2. OSM (Geofabrik extracts) filtered with `osmium tags-filter`, parsed from OPL; names split by script, "
          "`old_name*` marked historic. Extracted features are cached in `raw/cache/` keyed by the pbf sha256.",
          "3. OSM and GeoNames features merge into one entry when they share a `translit.match_key` (>=4 chars), "
          "are in the same feature class, and are within 5 km (15 km cities/pop>100k, 30 km districts/rivers, 100 km states).",
          "4. Curated places merge by key within 15 km (or by key alone when they have no coordinates and one high-rank match), "
          "else become new entries. Curated/lexicon names are all `expand=1`.",
          "5. Lexicon entries with the same id across the Sudan/Ukraine files merge into one `term:<id>` entry.", "",
          "Rebuild: `.venv/bin/python -m language_pair_search.gazetteer_build` (needs `osmium` on PATH for the OSM step; "
          "`--no-osm` skips it). The build writes a temp file and renames it atomically.", ""]
    if args_note:
        L += [args_note, ""]
    Path(path).write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------- spot checks
CHECKS = ["Bakhmut", "Artemovsk", "Артемовск", "Kyiv", "Kiev", "Mykolaiv", "Nikolaev", "El Fasher",
          "Al-Fashir", "الفاشر", "Zamzam", "زمزم", "Geneina", "الجنينة", "Omdurman", "ام درمان", "Wad Madani",
          "ود مدني", "Nova Kakhovka", "Olenivka", "Azovstal"]


def spot_checks(dbpath):
    con = sqlite3.connect(dbpath)
    for q in CHECKS:
        k = match_key(q)
        rows = con.execute("""SELECT e.id,e.label,e.country,e.category,e.rank,e.admin1 FROM entries e
            WHERE e.id IN (SELECT entry_id FROM names WHERE key=?) ORDER BY e.rank DESC LIMIT 4""", (k,)).fetchall()
        print(f"\n== {q}  (key '{k}')  {len(rows)}+ hits")
        for (i, lab, cc, cat, rk, adm) in rows:
            nm = con.execute("SELECT name,lang,historic FROM names WHERE entry_id=? AND expand=1 ORDER BY lang,name",
                             (i,)).fetchall()
            s = "; ".join(f"{n}[{l}{'/h' if h else ''}]" for n, l, h in nm[:14])
            print(f"  {i} {lab} | {cc} {cat} r{rk} {adm or ''} | {s}{' …' if len(nm) > 14 else ''}")
    con.close()


# ---------------------------------------------------------------- main
def find_pbf(pattern, want_md5=True):
    """-> (path, ok, reason)"""
    fs = sorted(RAW.glob(pattern))
    fs = [f for f in fs if not f.name.endswith(".md5")]
    if not fs:
        return None, False, "missing"
    f = fs[-1]
    md5f = Path(str(f) + ".md5")
    exp = EXPECTED_SIZE.get(f.name)
    if exp and f.stat().st_size != exp:
        return f, False, f"size {f.stat().st_size} != expected {exp} (still downloading?)"
    if md5f.exists():
        want = md5f.read_text().split()[0].lower()
        got = file_hashes(f)[0]
        if got != want:
            return f, False, f"md5 mismatch (incomplete download?) size={f.stat().st_size}"
    return f, True, "ok"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-osm", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default=str(GAZ / "dictionary.db"))
    ap.add_argument("--no-readme", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        spot_checks(a.out)
        return 0
    t0 = time.time()
    stats = collections.Counter()
    stats["junk"] = collections.Counter()
    sources, hashes = [], []
    all_ents = []
    osm_by_cc = {}
    for cc, cfg in COUNTRIES.items():
        gn = load_geonames(cc, stats)
        print(f"GeoNames {cc}: {len(gn)} features ({time.time()-t0:.0f}s)", flush=True)
        for p in (RAW / cc / f"{cc}.txt", RAW / f"alt_{cc}" / f"{cc}.txt"):
            sha = sha_only(p)
            hashes.append(sha)
            sources.append({"name": "GeoNames", "file": str(p.relative_to(RAW)), "sha256": sha,
                            "date": time.strftime("%Y-%m-%d", time.gmtime(p.stat().st_mtime)),
                            "license": "CC BY 4.0", "attribution": GN_ATTR})
        osm = []
        if not a.no_osm:
            pbf, ok, why = find_pbf(cfg["pbf"])
            if ok:
                md5, sha = file_hashes(pbf)
                hashes.append(sha)
                m = re.search(r"(\d{6})", pbf.name)
                sources.append({"name": "Geofabrik OpenStreetMap extract", "file": pbf.name, "sha256": sha,
                                "date": ("20" + m.group(1)) if m else "", "license": "ODbL 1.0", "attribution": OSM_ATTR})
                feats = extract_osm(pbf, cc, sha)
                for rec in feats:
                    e = osm_entry(rec, cc, stats)
                    if e:
                        osm.append(e)
                print(f"OSM {cc}: {len(osm)} usable features ({time.time()-t0:.0f}s)", flush=True)
            else:
                print(f"OSM {cc}: SKIPPED ({why})", flush=True)
                stats["osm_skipped_" + cc] += 1
        merged, idx = merge_osm(gn, osm, stats)
        all_ents.append((cc, merged, idx))
    places, idxs = [], {}
    for cc, merged, idx in all_ents:
        places += merged
        idxs[cc] = idx
    # curated merge needs one index per country; Index keys already include country
    big = Index()
    for e in places:
        big.add(e)
    used = apply_curated(places, big, stats)
    for fp in used:
        sha = sha_only(fp)
        hashes.append(sha)
        sources.append({"name": "Curated places", "file": str(fp.relative_to(HERE)), "sha256": sha, "date": "",
                        "license": "project-authored", "attribution": ""})
    terms, lexfiles = load_lexicon(stats)
    LEX_KEYS.clear()
    for t_ in terms:
        for (k_, l_) in t_.names:
            if " " not in k_:
                LEX_KEYS.add(k_)
    denyf = load_deny()
    if denyf:
        sha = sha_only(denyf)
        hashes.append(sha)
        sources.append({"name": "Ambiguous-name deny list", "file": str(denyf.relative_to(HERE)), "sha256": sha,
                        "date": "", "license": "project-authored", "attribution": ""})
    for fp in lexfiles:
        sha = sha_only(fp)
        hashes.append(sha)
        sources.append({"name": "Term lexicon", "file": str(fp.relative_to(HERE)), "sha256": sha, "date": "",
                        "license": "project-authored", "attribution": ""})
    fill_admin1(places)
    version = hashlib.sha256(("\n".join(sorted(hashes)) + "\n" + BUILDER_VERSION + "\nkeys" + str(getattr(translit, "KEY_VERSION", 1))).encode()).hexdigest()
    meta = {"built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "version": version,
            "builder": BUILDER_VERSION, "sources": sources,
            "key_version": str(getattr(translit, "KEY_VERSION", 1))}
    counts = write_db(a.out, places, terms, meta)
    note = ("Build stats: " + ", ".join(f"{k}={v}" for k, v in sorted(stats.items()) if k != "junk" and v))
    if not a.no_readme and Path(a.out).parent == GAZ:
        write_readme(GAZ / "BUILD.md", meta, counts, note)   # README.md is hand-written; build facts go here
    print("\nstats:", {k: v for k, v in stats.items() if k != "junk"})
    print("demoted to expand=0:", dict(DEMOTE))
    for r_, ex_ in DEMOTE_SAMPLES.items():
        print("  ", r_, ex_)
    print("junk names dropped (sample):", stats["junk"].most_common(15))
    print("counts:", json.dumps({k: v for k, v in counts.items() if k != "entries_by_country_kind_category"}, ensure_ascii=False))
    print(f"db: {a.out} {os.path.getsize(a.out)/1e6:.1f} MB; total {time.time()-t0:.0f}s")
    spot_checks(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
