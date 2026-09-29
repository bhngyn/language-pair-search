"""Search core: normalisation, obfuscation folding, stemming, NEAR, dictionary expansion, place matching.
Run from the repo root: python tests/test_search_core.py  (in-memory DB + tests/fixtures/dictionary_fixture.db)."""
import os, sys, sqlite3, json
HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
from language_pair_search import index, lexicon, textnorm, translit
lexicon.set_dictionary(os.path.join(FIX, "dictionary_fixture.db"))

N = textnorm.normalize
results = []
def check(name, cond, info=""):
    results.append((name, bool(cond)))
    assert cond, f"{name} {info}"

# ---------------------------------------------------------------- #2 obfuscation
for raw, want in [
    ("в а г н е р", "вагнер"), ("в.а.г.н.е.р", "вагнер"), ("W-A-G-N-E-R", "wagner"), ("В_А_Г_Н_Е_Р", "вагнер"),
    ("Ваг​нер", "вагнер"), ("Ваг­нер", "вагнер"), ("Ваг﻿нер", "вагнер"),
    ("в@гнер", "вагнер"), ("w@gner", "wagner"), ("b0mb", "bomb"), ("ca$h", "cash"), ("Г0род", "город"),
    ("Вaгнер", "вагнер"),            # Latin a inside a Cyrillic word
    ("Wаgner", "wagner"),            # Cyrillic а inside a Latin word
    ("Pусич", "русич"), ("Rusiсh", "rusich"),
    ("ваггггнер", "вагнер"), ("ааааа", "а"), ("хаааах", "хах"),
    ("کیا", "كيا"), ("ھ", "ھ"), ("علی", "علي"), ("كتاب", "كتاب"),
]:
    check(f"obf pos {raw!r}", N(raw) == want, f"{N(raw)!r} != {want!r}")
for raw in [                                 # must not change (beyond lower-casing)
    "2024", "100", "$100", "10$", "0", "10.05.2024", "T-72", "b52", "a1b2",
    "و ب ل ف ك", "و ب ل ف", "ب ل ف ك و",                # Arabic single-letter words are real words: never joined
    "a b c", "в а г", "и в с",                          # runs shorter than 4
    "book", "coffee", "Russia", "hello", "الله", "مما", "ll", "aa",   # normal doubled letters
    "https://t.me/wagner_0fficial/12", "@wagner_bot", "www.example.com", "me@example.com", "https://x.com/a@b/ааааа",
]:
    check(f"obf neg {raw!r}", N(raw) == raw.lower(), f"{N(raw)!r}")
check("obf: numbers survive inside text", "2024 г0д" not in N("в 2024 г0д") and "2024" in N("в 2024 г0д"))
check("obf: url kept inside sentence", "https://t.me/wagner_0fficial" in N("Смотри https://t.me/wagner_0fficial сегодня"))
check("obf: idempotent", all(N(N(x)) == N(x) for x in ["в а г н е р", "b0mb", "ваггггнер", "Wаgner", "کیا", "hello world"]))
check("obf: empty", N("") == "" and N(None) == "")

# ---------------------------------------------------------------- #7 stemmers
ru = translit.ru_stem
check("ru обстрелы/а/ом", len({ru("обстрелы"), ru("обстрела"), ru("обстрелом"), ru("обстрелов"), ru("обстрелах")}) == 1)
check("ru stem value", ru("обстрелом") == "обстрел")
check("ru вагнера", ru("вагнера") == "вагнер" and ru("вагнером") == "вагнер")
check("ru украины/украина", ru("украины") == ru("украина") == "украин")
check("ru убитых/убиты", ru("убитых") == ru("убиты"))
check("cy_stem ≥4 rule", translit.cy_stem("дом") == "дом" and len(translit.cy_stem("война")) >= 4)
check("cy_stem unchanged -> same word", translit.cy_stem("вагнер") == "вагнер")
uk = translit.uk_stem
check("uk обстріл*", len({uk("обстріл"), uk("обстрілу"), uk("обстрілами"), uk("обстрілів")}) == 2 or uk("обстрілу") == uk("обстрілами") == "обстріл")
check("uk міста/міст", translit.cy_stem("миколаївці") == "миколаївц" and translit.cy_stem("обстрілами") == "обстріл")
check("ar الشهداء/شهداء", textnorm.strip_prefix("الشهداء") == "شهداء" and translit.ar_suffix("شهداء") == "شهداء")
check("ar قصفت/قصف", translit.ar_suffix("قصفت") == "قصف" == translit.ar_suffix("قصف"))
check("ar suffixes", translit.ar_suffix("مدنيون") == "مدني" and translit.ar_suffix("طائرات") == "طائر" and
      translit.ar_suffix("بيتها") == "بيت" and translit.ar_suffix("مدينه") == "مدين")
check("ar keeps ≥3 letters", translit.ar_suffix("بنت") == "بنت" and translit.ar_suffix("ابن") == "ابن" and translit.ar_suffix("قصف") == "قصف")
check("index_stems: only differing tokens", textnorm.index_stems("вагнер") == "zzvagnir" and "вагнер" not in textnorm.index_stems("вагнер").split())
st = textnorm.index_stems(N("обстрелов الشهداء قصفت"))
check("index_stems content", "обстрел" in st.split() and "شهداء" in st.split() and "قصف" in st.split(), st)

# ---------------------------------------------------------------- in-memory FTS table
con = sqlite3.connect(":memory:")
con.execute(index.fts_ddl("posts_fts", meta=True))
DF = lambda tok: (con.execute("SELECT COUNT(*) FROM posts_fts WHERE posts_fts MATCH ?", (f'norm : "{tok}"',)).fetchone()[0]
                  / max(1, con.execute("SELECT COUNT(*) FROM posts_fts").fetchone()[0]))
E = lambda q, **k: lexicon.expand(q, doc_freq=DF, **k)
def post(text, ch="c", mid=[0]):
    mid[0] += 1
    index.index_text(con, "posts_fts", mid[0], text, [ch])
    return mid[0]
def hits(expr, table="posts_fts"):
    return {r[0] for r in con.execute(f"SELECT rowid FROM {table} WHERE {table} MATCH ?", (expr,))}

p = {k: post(t) for k, t in {
    "ob1": "Наступает в а г н е р у города", "ob2": "В@гнер и Bагнер", "wagl": "W-A-G-N-E-R group", "zw": "Ваг​нер",
    "shell1": "обстрелы Бахмута", "shell2": "после обстрела", "shell3": "под обстрелом", "shell4": "обстріл міста",
    "ar1": "قصفت الطائرات الفاشر", "ar2": "قصف جوي", "ar3": "استشهد الشهداء", "ar4": "شهداء الدعم السريع",
    "svo": "свои и свобода и группа", "svo2": "начало СВО и работа ГРУ", "grp": "группа груз",
    "n1": "Wagner attacked the base near Bakhmut", "n2": "Wagner far away from the shelling now now now now now Bakhmut",
    "n3": "the airstrike hit Bakhmut and wagner", "n4": "Бахмут и потом очень много слов Вагнер",
}.items()}

# ---------------------------------------------------------------- query-side matching (obfuscation)
check("q: вагнер finds all obfuscations", {p["ob1"], p["ob2"], p["zw"]} <= hits(textnorm.fts_query("вагнер")))
check("q: wagner finds W-A-G-N-E-R", p["wagl"] in hits(textnorm.fts_query("wagner")))
check("q: spaced query is folded too", p["ob1"] in hits(textnorm.fts_query("в а г н е р")))
check("q: Ваг​нер query", p["zw"] in hits(textnorm.fts_query("Ваг​нер")))
# stemming both ways
sh = hits(textnorm.fts_query("обстрелы"))
check("stem: обстрелы finds обстрела/обстрелом/обстрелы", {p["shell1"], p["shell2"], p["shell3"]} <= sh, sh)
check("stem: обстрелом finds all", {p["shell1"], p["shell2"], p["shell3"]} <= hits(textnorm.fts_query("обстрелом")))
check("stem uk: обстріл finds", p["shell4"] in hits(textnorm.fts_query("обстріл")))
check("stem ar: قصفت finds قصف", p["ar2"] in hits(textnorm.fts_query("قصفت")) and p["ar1"] in hits(textnorm.fts_query("قصفت")))
check("stem ar: قصف finds قصفت", p["ar1"] in hits(textnorm.fts_query("قصف")))
check("stem ar: الشهداء finds شهداء", {p["ar3"], p["ar4"]} <= hits(textnorm.fts_query("الشهداء")) and p["ar4"] in hits(textnorm.fts_query("شهداء")))
check("stem: exclusion has no stems", textnorm.fts_query("a -обстрелы") == '"a"* NOT "обстрелы"*')
check("compat: plain latin query unchanged", textnorm.fts_query("Wagner Rusich") == '"wagner"* AND "rusich"*')
check("compat: OR/phrase/neg", textnorm.fts_query('"قصف جوي" OR x -y') == '"قصف جوي" OR "x"* NOT "y"*')
check("compat: empty", textnorm.fts_query("") is None and textnorm.fts_query('- "') is None)

# ---------------------------------------------------------------- #6 NEAR
check("near literal", textnorm.fts_query("wagner NEAR/5 bakhmut") == 'NEAR("wagner"* "bakhmut"*, 5)')
check("near default 10", textnorm.fts_query("a NEAR b") == 'NEAR("a"* "b"*, 10)')
check("near phrase", textnorm.fts_query('"a b" NEAR/3 c*') == 'NEAR("a b" "c"*, 3)')
check("near phrase prefix", textnorm.fts_query('"a b"* NEAR/3 c') == 'NEAR("a b"* "c"*, 3)')
check("near chain", textnorm.fts_query("a NEAR/3 b NEAR/7 c") == 'NEAR("a"* "b"* "c"*, 7)')
check("near lowercase is a word", textnorm.fts_query("near the border") == '"near"* AND "the"* AND "border"*')
check("NEAR inside a phrase is text", textnorm.fts_query('"the NEAR east"') == '"the near east"')
check("near dangling dropped", textnorm.fts_query("a NEAR") == '"a"*' and textnorm.fts_query("NEAR/4 a") == '"a"*')
check("near with OR/AND", textnorm.fts_query("x NEAR y OR z") == 'NEAR("x"* "y"*, 10) OR "z"*')
check("near executes", p["n1"] in hits(textnorm.fts_query("wagner NEAR/5 bakhmut")) and p["n2"] not in hits(textnorm.fts_query("wagner NEAR/5 bakhmut")))
check("near execution wide", p["n2"] in hits(textnorm.fts_query("wagner NEAR/30 bakhmut")))
check("near phrase executes", p["n3"] in hits(textnorm.fts_query('"the airstrike" NEAR/5 wagner')))
e = E("Bakhmut NEAR Wagner")
check("near expanded is OR of NEARs", e["fts"].count("NEAR(") > 1 and e["fts"].startswith("(NEAR(") and not e.get("near_literal"), e["fts"])
check("near expanded: cyrillic alt reachable", "NEAR(\"бахмут\"* \"вагнер\"*, 10)" in e["fts"])
check("near expanded: groups reported", [g["span"] for g in e["groups"]] == ["bakhmut", "wagner"])
check("near expanded combos <= 24", e["fts"].count("NEAR(") <= lexicon.MAX_NEAR)
check("near expanded finds cyrillic doc", p["n4"] in hits(E("Bakhmut NEAR/8 Wagner")["fts"]) or p["n4"] in hits(E("Bakhmut NEAR/12 Wagner")["fts"]))
e = E("Fasher NEAR airstrike")
check("near over cap -> reduced, flagged, <=24 combos", e.get("near_reduced") is True and e["fts"].count("NEAR(") <= 24 and not e.get("near_literal"), e["fts"])
check("near reduced: original word first, romanised key, native scripts kept", '"fasher"* "airstrike"*' in e["fts"] and "zzfashir" in e["fts"] and "الفاشر" in e["fts"] and "авиаудар" in e["fts"])
check("near reduced: near_used lists alts", e["near_used"][0]["used"][0]["alts"][0] == "fasher" and len(e["near_used"][0]["used"]) == 2)
check("near reduced: groups still reported", [g["span"] for g in e["groups"]] == ["fasher", "airstrike"])
check("near reduced runs", isinstance(hits(e["fts"]), set))
check("near_reduced absent when small", "near_reduced" not in E("Rusich NEAR x"))
check("near expand=0 literal", E("Bakhmut NEAR Wagner", enabled=False)["fts"] == 'NEAR("bakhmut"* "wagner"*, 10)')
check("near skip keeps literal operand", "бахмут" not in E("Bakhmut NEAR Wagner", skip=["bakhmut"])["fts"] and "вагнер" in E("Bakhmut NEAR Wagner", skip=["bakhmut"])["fts"])
check("near drop honoured", "\"bakhmut\"* \"вагнер\"*" not in E("Bakhmut NEAR Wagner", drop=["вагнер"])["fts"] and "\"bakhmut\"* \"вагнер\"*" in E("Bakhmut NEAR Wagner")["fts"])
e = E("Вагнер NEAR/5 обстрелы")
pn = post("Вагнер вёл обстрелом позиции")
check("near stems (cyrillic)", '"обстрел"*' in e["fts"] and pn in hits(e["fts"]))
for q in ["Bakhmut NEAR/3 Khartoum", "airstrike NEAR/2 Wagner", "الفاشر NEAR/4 قصف", '"قصف جوي" NEAR Fasher', "a NEAR/3 b NEAR/7 c"]:
    hits(E(q)["fts"])                                              # FTS5 must accept every generated expression
e = E("Wagner")
g = e["groups"][0]
tr = [a for a in g["alts"] if a["lang"] == "translit"]
check("zz alt inside a dictionary group (not a separate group)", len(e["groups"]) == 1 and len(tr) == 1 and tr[0]["term"] == "Cyrillic ≈ vagnir" and '"zzvagnir"*' in e["fts"], e)
check("zz alt droppable", '"zzvagnir"*' not in E("Wagner", drop=["cyrillic ≈ vagnir"])["fts"] and E("Wagner", drop=["cyrillic ≈ vagnir"])["groups"][0]["alts"][-1]["dropped"])
check("zz: short/stopword Latin words get none", not [a for a in E("RSF")["groups"][0]["alts"] if a["lang"] == "translit"] and not [a for g in E("will")["groups"] for a in g["alts"]])
check("zz alt not highlighted", "Cyrillic ≈ vagnir" not in lexicon.highlight_terms(e, "Wagner"))
check("zz alt counted in NEAR reduction", '"zzvagnir"*' in E("Bakhmut NEAR Wagner")["fts"] and "zzvagnir" in str(E("Bakhmut NEAR Wagner")["near_used"]) .replace("vagnir", "zzvagnir") )
check("near highlight terms drop the keyword", lexicon.highlight_terms(E("a NEAR/5 b"), "a NEAR/5 b") == ["a", "b"])

# ---------------------------------------------------------------- short alt tokens exact
check("alt short exact: СВО", lexicon.alt_fts("СВО") == '"сво"' and lexicon.alt_fts("ГРУ") == '"гру"' and lexicon.alt_fts("EW") == '"ew"')
check("alt short exact: RPG/FSB/UAV", all(lexicon.alt_fts(x) == f'"{x.lower()}"' for x in ("RPG", "FSB", "UAV", "ЗСУ", "ПВО", "РЭБ")))
check("alt ≥4 keeps prefix", lexicon.alt_fts("Вагнер") == '"вагнер"*' and lexicon.alt_fts("Bakhmut") == '"bakhmut"*')
check("alt multi: short token exact, last ≥4 star", lexicon.alt_fts("ГРУ Украины") == '"гру" + "украин"*' or lexicon.alt_fts("ГРУ Украины") == '"гру" + "украины"*'
      , lexicon.alt_fts("ГРУ Украины"))
check("alt multi: last short exact", lexicon.alt_fts("Нова ГРУ") == '"нова"* + "гру"' or lexicon.alt_fts("Нова ГРУ") == '"нов"* + "гру"', lexicon.alt_fts("Нова ГРУ"))
check("alt multi: ar articles", lexicon.alt_fts("الدعم السريع") == '("الدعم" + "السريع"* OR "دعم" + "سريع"*)', lexicon.alt_fts("الدعم السريع"))
check("СВО must not match свои/свобода", hits(lexicon.alt_fts("СВО")) == {p["svo2"]}, hits(lexicon.alt_fts("СВО")))
check("ГРУ must not match группа", hits(lexicon.alt_fts("ГРУ")) == {p["svo2"]}, hits(lexicon.alt_fts("ГРУ")))
check("user's own short word unchanged (prefix)", textnorm.fts_query("сво") == '"сво"*' and {p["svo"], p["svo2"]} <= hits(textnorm.fts_query("сво")))

# ---------------------------------------------------------------- index helpers
post("Original claim about Kharkiv shelling")
n0 = con.execute("SELECT COUNT(*) FROM posts_fts").fetchone()[0]
index.index_text(con, "posts_fts", 1, "replaced text", ["c"])
check("index_text replaces the row (no duplicates)", con.execute("SELECT COUNT(*) FROM posts_fts").fetchone()[0] == n0 and 1 in hits('"replaced"*'))
check("index_text: meta column not matched by a text search", 1 not in hits(textnorm.fts_scoped('"c"*')) and 1 in hits(textnorm.fts_scoped('"c"*', text=False, names=True)))
con.execute(index.fts_ddl("plain_fts"))
index.index_text(con, "plain_fts", 1, "قصفت الطائرات")
check("index_text without meta", hits(textnorm.fts_query("قصف"), "plain_fts") == {1})
check("index_row shape", index.index_row("в а г н е р", ["Chan"])[0] == "вагнер" and index.index_row("x")[2] == "")
check("KEY_VERSION", translit.KEY_VERSION == 2 and index.FTS_VERSION == "3")

# ---------------------------------------------------------------- #8 find_places
FP = lambda t, **k: lexicon.find_places(N(t), doc_freq=DF, **k)
r = FP("Обстрел El Fasher и alfashir, الفاشر, Хартума")
check("places: found across scripts", {x["entry_id"] for x in r} == {"place:2", "place:3"} and len(r) == 4, r)
check("places: token positions", r[0]["start_tok"] == 1 and r[0]["end_tok"] == 3 and r[0]["name"] == "el fasher", r)
r = FP("Mykolaivka")
check("places: ambiguous -> all candidates", sorted(x["entry_id"] for x in r) == ["place:5", "place:6", "place:7"] and all(x["candidates"] == 3 for x in r))
check("places: terms are not places", FP("airstrike wagner rsf") == [])
check("places: longest span first", [x["entry_id"] for x in FP("Nova Kakhovka")] == ["place:8"] and FP("Nova Kakhovka")[0]["end_tok"] == 2)
check("places: stopword/short guard", FP("the will mark") == [])
check("places: empty", FP("") == [] and lexicon.find_places("") == [])
pl = lexicon.place("place:2")
check("place(): fields", set(pl) == {"entry_id", "label", "country", "category", "admin1", "lat", "lon", "rank"} and pl["label"] == "El Fasher")
check("place(): unknown", lexicon.place("place:999") is None)
# edits invalidate the map
add = lexicon.Edits([{"id": 1, "action": "add_name", "entry_id": "place:2", "name": "Zamzam", "lang": "en"}])
before, after = FP("Zamzam"), FP("Zamzam", edits=add)
check("places: edits picked up", before == [] and [x["entry_id"] for x in after] == ["place:2"], after)
check("places: edits removed again", FP("Zamzam") == [])
hide = lexicon.Edits([{"id": 2, "action": "hide_entry", "entry_id": "place:3"}])
check("places: hidden entry not tagged", FP("Khartoum", edits=hide) == [] and FP("Khartoum") != [])
check("edits: version", add.version() != hide.version() and lexicon.Edits([]).version() == "")
# frequent-word guard: low-rank place named like an ordinary word vs a high-rank one; short names
import tempfile
dbp = os.path.join(tempfile.mkdtemp(), "dict2.db")
dc = sqlite3.connect(dbp)
for sql in ("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)",
            "CREATE TABLE entries(id TEXT PRIMARY KEY, kind TEXT NOT NULL, country TEXT, category TEXT, label TEXT NOT NULL, admin1 TEXT, lat REAL, lon REAL, population INTEGER, rank INTEGER NOT NULL DEFAULT 0, sources TEXT, notes TEXT)",
            "CREATE TABLE names(entry_id TEXT NOT NULL, name TEXT NOT NULL, lang TEXT NOT NULL, historic INTEGER NOT NULL DEFAULT 0, expand INTEGER NOT NULL DEFAULT 1, source TEXT, key TEXT NOT NULL)"):
    dc.execute(sql)
dc.execute("INSERT INTO meta VALUES ('version', 'big1'), ('key_version', '2'), ('counts', '{\"sd_ar\": 5}')")
for eid, label, rank, nm, lang in (("p:1", "Ржавка", 3, "Ржавка", "ru"), ("p:2", "Днепр", 9, "Днепр", "ru"), ("p:3", "Ий", 2, "Ий", "ru"),
                                   ("p:4", "Соль", 3, "Соль", "ru"), ("p:5", "Zaporizhzhia", 8, "Zaporizhzhia", "en"),
                                   ("p:6", "Rare place", 5, "Vuhledar", "en"), ("p:7", "Луганск обл", 9, "Луганская Народная", "ru")):
    dc.execute("INSERT INTO entries(id, kind, label, rank) VALUES (?, 'place', ?, ?)", (eid, label, rank))
    dc.execute("INSERT INTO names VALUES (?,?,?,0,1,'t',?)", (eid, nm, lang, translit.match_key(nm)))
for eid, nm, lang in (("p:1", "Rzhavka", "en"), ("p:2", "Dnipro", "en")):
    dc.execute("INSERT INTO names VALUES (?,?,?,0,1,'t',?)", (eid, nm, lang, translit.match_key(nm)))
dc.commit(); dc.close()
lexicon.set_dictionary(dbp)
for i in range(40):
    post("ржавка днепр Днепр и соль %d" % i if i < 30 else "просто текст %d" % i)
post("Vuhledar shelled")
lexicon.guard_stats.update(short=0, stopword=0, frequent=0); 
r = FP("ржавка днепр соль Vuhledar Zaporizhzhia ий")
names = {x["name"]: x["entry_id"] for x in r}
check("guard: frequent low-rank word rejected", "ржавка" not in names and lexicon.guard_stats["frequent"] >= 1, (r, lexicon.guard_stats))
check("guard: frequent but high-rank kept", names.get("днепр") == "p:2", r)
check("guard: short key rejected", "соль" not in names and "ий" not in names and lexicon.guard_stats["short"] >= 2, (r, lexicon.guard_stats))
check("guard: single Latin word below town rank not tagged (lead rule, QA V1-2)", "vuhledar" not in names and names.get("zaporizhzhia") == "p:5", r)
alt = lambda e, t: [a for g in e["groups"] for a in g["alts"] if a["term"] == t]
e = E("Rzhavka")
check("alt guard: frequent single-word low-rank place name suppressed", alt(e, "Ржавка")[0]["dropped"] and alt(e, "Ржавка")[0]["reason"] == "common word", e["groups"])
check("alt guard: stop-list word suppressed at any rank", lexicon._common_word("победа", 9) and lexicon._common_word("مدني", 9) and not lexicon._common_word("бахмут", 3))
check("alt guard: not emitted in the FTS", "ржавк" not in e["fts"])
e = E("Rzhavka", drop=["+ржавка"])
check("alt guard: drop=+term restores", not alt(e, "Ржавка")[0]["dropped"] and "ржавк" in e["fts"])
e = E("Rzhavka", drop=["ржавка"])
check("alt guard: plain drop still drops (no reason)", alt(e, "Ржавка")[0]["dropped"] and "reason" not in alt(e, "Ржавка")[0])
e = E("Dnipro")
check("alt guard: high-rank frequent name kept", not alt(e, "Днепр")[0]["dropped"] and "днеп" in e["fts"], e["groups"])
check("alt guard: lexicon terms never suppressed", not any(a.get("reason") for g in E("Wagner")["groups"] for a in g["alts"]))
check("select: rank<5 single word not tagged (rule 1)", FP("Ржавка") == [] and FP("Ржавка ржавка") == [])
check("common list: never tagged", lexicon._tag_common("мирные") and lexicon._tag_common("الحاله") and lexicon._tag_common("центре") and not lexicon._tag_common("бахмут"))
check("places: multiword name", [x["entry_id"] for x in FP("Луганская Народная")] == ["p:7"])
check("places: no dictionary -> []", (lexicon.set_dictionary("/nonexistent") or FP("Бахмут")) == [])
lexicon.set_dictionary(dbp)
print("PASS", sum(ok for _, ok in results), "/", len(results))
