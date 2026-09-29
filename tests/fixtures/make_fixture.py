"""Build a small fixture dictionary.db following the spec schema exactly."""
import os, sqlite3, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from language_pair_search import translit

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dictionary_fixture.db")
if os.path.exists(OUT): os.remove(OUT)
con = sqlite3.connect(OUT)
con.executescript("""
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE entries(id TEXT PRIMARY KEY, kind TEXT NOT NULL, country TEXT, category TEXT, label TEXT NOT NULL,
  admin1 TEXT, lat REAL, lon REAL, population INTEGER, rank INTEGER NOT NULL DEFAULT 0, sources TEXT, notes TEXT);
CREATE TABLE names(entry_id TEXT NOT NULL, name TEXT NOT NULL, lang TEXT NOT NULL, historic INTEGER NOT NULL DEFAULT 0,
  expand INTEGER NOT NULL DEFAULT 1, source TEXT, key TEXT NOT NULL);
CREATE INDEX names_key ON names(key);
CREATE INDEX names_entry ON names(entry_id);
""")
n = [0]
def entry(kind, country, cat, label, admin1, rank, names, id=None):
    n[0] += 1
    eid = id or f"place:{n[0]}"
    con.execute("INSERT INTO entries(id,kind,country,category,label,admin1,rank,sources) VALUES (?,?,?,?,?,?,?,'[\"curated\"]')",
                (eid, kind, country, cat, label, admin1, rank))
    seen = set()
    for nm in names:
        name, lang, *fl = nm
        flags = set(fl)
        key = translit.match_key(name)
        if len(key) < 3 or (eid, key, lang) in seen: continue
        seen.add((eid, key, lang))
        con.execute("INSERT INTO names VALUES (?,?,?,?,?,?,?)",
                    (eid, name, lang, int("historic" in flags), 0 if "expand0" in flags else 1,
                     "lexicon" if kind == "term" else "curated", key))
entry("place","UA","city","Bakhmut","Donetsk Oblast",8,[("Bakhmut","en"),("Бахмут","uk"),("Бахмут","ru"),
      ("Артемовск","ru","historic"),("Артемівськ","uk","historic"),("Artemivsk","latn","expand0")])
entry("place","SD","city","El Fasher","North Darfur",8,[("El Fasher","en"),("الفاشر","ar"),("Al-Fashir","latn","expand0")])
entry("place","SD","city","Khartoum","Khartoum",9,[("Khartoum","en"),("الخرطوم","ar"),("Хартум","ru")])
entry("place","SD","city","Omdurman","Khartoum",8,[("Omdurman","en"),("ام درمان","ar")])
for adm, r in (("Kyiv Oblast",5),("Zaporizhzhia Oblast",5),("Mykolaiv Oblast",5)):
    entry("place","UA","village","Mykolaivka",adm,r,[("Mykolaivka","en"),("Миколаївка","uk"),("Николаевка","ru")])
entry("place","UA","town","Nova Kakhovka","Kherson Oblast",7,[("Nova Kakhovka","en"),("Нова Каховка","uk"),("Новая Каховка","ru")])
entry("term",None,"attack","airstrike",None,0,[("airstrike","en"),("air strike","en"),("غارة جوية","ar"),("قصف جوي","ar"),
      ("غارة","ar"),("الطيران","ar"),("авиаудар","ru"),("авіаудар","uk")],id="term:airstrike")
entry("term",None,"actor","RSF",None,0,[("RSF","en"),("Rapid Support Forces","en"),("الدعم السريع","ar"),("الدعامة","ar"),("جنجويد","ar")],id="term:rsf")
entry("term",None,"actor","Wagner",None,0,[("Wagner","en"),("Вагнер","ru"),("ЧВК Вагнер","ru"),("вагнеровц","ru")],id="term:wagner")
con.executemany("INSERT INTO meta VALUES (?,?)", [("built_at","2026-09-28T00:00:00Z"),("version","fixture0000000000000000000000000000000000000000"),
    ("sources",'[{"name":"fixture","file":"-","sha256":"0","date":"2026-09-28","license":"n/a","attribution":"test fixture"}]'),("counts","{}")])
con.commit()
print(OUT, con.execute("select count(*) from entries").fetchone(), con.execute("select count(*) from names").fetchone())
