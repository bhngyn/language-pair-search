"""Golden vectors for the JS port of the query side (js/lpsq.mjs).

Runs this checkout's Python `language_pair_search` (src/) over a large, diverse input set and writes
tests/golden/lps_query.json (git-ignored, ~10 MB), which tests/js/lpsq.test.mjs checks the JS module against.

    python scripts/golden.py            # write the golden file
    python scripts/golden.py --tables   # print the Unicode tables to paste into js/lpsq.mjs

No dictionary.db is used (expand() then only adds Cyrillic-romanisation groups); the script refuses to run
if one is configured. Inputs are synthetic word lists plus the names in this repository's own lexicons and
curated place lists. Deterministic: same code + same Python Unicode version -> same file.
"""

import json
import os
import random
import re
import sys
import unicodedata
from pathlib import Path

os.environ.pop("LANGUAGE_PAIR_DICT", None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from language_pair_search import index, lexicon, textnorm, translit  # noqa: E402

OUT = ROOT / "tests" / "golden" / "lps_query.json"
DATA = ROOT / "src" / "language_pair_search" / "data"


# --------------------------------------------------------------------------- #
# Unicode tables (Python's own classification; the JS module embeds them)
# --------------------------------------------------------------------------- #

def _ranges(pred):
    out, start = [], None
    for c in range(0x110000):
        ok = not (0xD800 <= c <= 0xDFFF) and pred(chr(c))
        if ok and start is None:
            start = c
        elif not ok and start is not None:
            out.append((start, c - 1))
            start = None
    if start is not None:
        out.append((start, 0x10FFFF))
    return out


def _b36(n):
    s = ""
    while True:
        n, r = divmod(n, 36)
        s = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + s
        if not n:
            return s


def _encode(ranges):
    """Compact range list: comma-separated `gap[-len]` in base 36, gap measured from the previous range end."""
    parts, prev = [], 0
    for a, b in ranges:
        parts.append(_b36(a - prev) + ("-" + _b36(b - a) if b > a else ""))
        prev = b
    return ",".join(parts)


def unicode_tables():
    w, d, s = re.compile(r"\w"), re.compile(r"\d"), re.compile(r"\s")
    t = {
        "word": _encode(_ranges(lambda ch: bool(w.match(ch)))),                       # re \w
        "alnum": _encode(_ranges(lambda ch: bool(w.match(ch)) and ch != "_")),        # [^\W_]
        "letter": _encode(_ranges(lambda ch: bool(w.match(ch)) and ch != "_" and not d.match(ch))),  # [^\W\d_]
        "digit": _encode(_ranges(lambda ch: bool(d.match(ch)))),                      # re \d
        "space": _encode(_ranges(lambda ch: bool(s.match(ch)))),                      # re \s (= str.isspace/strip)
        "alpha": _encode(_ranges(str.isalpha)),                                       # str.isalpha
        "combining": _encode(_ranges(lambda ch: unicodedata.combining(ch) != 0)),     # unicodedata.combining
    }
    # the JS port reuses `alnum` for str.isalnum and `space` for str.strip(): both must be the same sets
    assert t["alnum"] == _encode(_ranges(str.isalnum)) and t["space"] == _encode(_ranges(str.isspace))
    return t


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #

EN = """the human rights council special rapporteur arbitrary detention torture enforced disappearance freedom expression
assembly association defenders journalists women girls children migrants refugees asylum seekers indigenous peoples
minorities extrajudicial executions summary killings government excellency allegations information received concerning
communication letter reply urgent appeal allegation independence judges lawyers counter terrorism security legislation
bill draft law amendment prison prisoner detainee hunger strike health food water sanitation housing education environment
toxic waste business transnational corporations mercenaries slavery trafficking sale exploitation violence discrimination
racism xenophobia religion belief privacy displaced persons internally leprosy albinism older persons disabilities poverty
cultural rights development solidarity truth justice reparation guarantees non-recurrence kyiv kiev kharkiv kharkov odesa
odessa bakhmut artemivsk mariupol zaporizhzhia donetsk luhansk lugansk crimea sevastopol mykolaiv nikolayev kherson
khartoum omdurman darfur el fasher al-fashir geneina nyala kordofan sudan chad yemen sanaa aden syria damascus aleppo idlib
gaza rafah khan younis jerusalem ramallah hebron jenin nablus lebanon beirut iraq baghdad mosul iran tehran
afghanistan kabul kandahar myanmar yangon rakhine rohingya china xinjiang uyghur tibet hong kong beijing russia moscow
belarus minsk ukraine wagner legion akhmat battalion brigade regiment shelling airstrike drone missile artillery
will mark hill john smith o'brien d'artagnan rock-n-roll e-mail co-operation state-of-the-art twenty-first well-being
tchaikovsky shchukin khrushchev yaroslavl zhytomyr chernihiv chernobyl kropyvnytskyi yalta yasinuvata mykolayiv
artyomovsk djokovic joseph jordan philosophy phone xavier quixote""".split()

FR = """liberté égalité fraternité détention arbitraire défenseurs droits l'homme réfugiés été où là çà garçon façade
noël naïve maïs cœur œuvre sœur ægis élève éléphant hôpital forêt île âge déjà très préoccupé allégations
concernant gouvernement excellence informations reçues l'arrestation d'un journaliste qu'il aujourd'hui
Côte d'Ivoire Sénégal Bénin Guinée Mali Niger Tchad Cameroun République démocratique Congo""".split()

ES = """detención arbitraria niños niñas mañana señor año español corazón acción información relación pingüino
güero cigüeña desaparición forzada ejecución extrajudicial México Perú Colombia Bogotá Medellín Cádiz Málaga
Nicaragua Panamá Ecuador Venezuela Guatemala Honduras El Salvador Paraguay Uruguay Bolivia""".split()

PT = """detenção ação informação coração não são mãe pão João São Paulo Brasília Maranhão Pará Amapá
Moçambique Angola Guiné-Bissau Cabo Verde Timor-Leste defensores direitos humanos cônsul atenção""".split()

TR = """İstanbul Istanbul ıstakoz Iğdır İzmir Şanlıurfa Diyarbakır Gaziantep Çanakkale Eskişehir ağaç
öğretmen gözaltı işkence ifade özgürlüğü Türkiye Kürt Ağrı Muş Bitlis Şırnak Hakkâri ŞİŞLİ ÇİĞ ılık İLK
gümüş çiçek üzüm düğün""".split()

DE_MISC = """Straße STRASSE Maß Größe groß Fußball ẞ ß Ελλάδα ΣΟΦΟΣ Σοφός ΟΔΟΣ Ὀδυσσεύς ﬁnance ﬂag ﬀ
Ⅻ ½ ² ³ ℃ № ™ ℌ ℍ ﬃ ǅ ǈ ǋ Ǳ ΐ ﬆ""".split()

AR = """الخرطوم أم درمان الفاشر الجنينة نيالا دارفور كردفان السودان تشاد اليمن صنعاء عدن سوريا دمشق حلب إدلب غزة
رفح خان يونس القدس رام الله الخليل جنين نابلس لبنان بيروت العراق بغداد الموصل إيران طهران قوات الدعم السريع
الجيش السوداني القصف الجوي الغارات غارة جوية المدنيين الشهداء والمدارس والسيارات بالمستشفى للمدينة كالأسد
فالحرب وسيقول سيذهبون المقاتلون المقاتلين الطائرات المسيرة مسيرة قصفت قصفوا مدرستها كتبهم كتابهن كتابكم
بيتنا قريته العربية مدينة مكتبة مسؤول مسئول مؤتمر سؤال رئيس هيئة شؤون إسرائيل آمن آية أحمد إبراهيم مصطفى موسى
عيسى يحيى على إلى حتى فى ابن بنت عبدالله عبد الله ٱلرحمن""".split()

AR_TASHKEEL = ["مُحَمَّد", "الْخَرْطُوم", "كِتَابٌ", "قَصْفٌ", "مَدْرَسَةٌ", "عَلَىٰ", "إِنَّ", "ٱلْحَمْدُ", "الـــخرطوم",
               "مــدرسة", "قصـــف", "غزةّ", "سُودَانِيّ"]

FA = """تهران ایران کرمان یزد شیراز اصفهان مشهد کابل هرات قندهار فارسی زندگی کتاب یک دو سه چهار پنج گفتگو
آزادی زن زندگی خانه\u200cها می\u200cخواهم نمی\u200cدانم پیش ژاله گچ پول چای کودک دیگر""".split()

DIGITS = ["٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹", "١٩٤٨", "۱۴۰۳", "2024", "١٢٣abc", "abc۴۵۶", "٣٠ قتيلا", "۲۰ کشته", "𝟏𝟐𝟑",
          "१२३", "১২৩", "١٢٫٥", "٪٥٠"]

RU = """Киев Київ Харьков Харків Одесса Одеса Бахмут Артемовск Артемівськ Мариуполь Маріуполь Запорожье Запоріжжя
Донецк Донецьк Луганск Луганськ Крым Крим Севастополь Николаев Миколаїв Херсон Москва Белгород Курск Брянск
Белоруссия Беларусь Минск Россия Украина Україна Вагнер Ахмат батальон бригада полк обстрел обстрелом обстрелы
обстрілів удар ударов ударами беспилотник беспилотники беспилотников дрон дронов ракета ракеты ракетой артиллерия
артиллерийский военнослужащие военнослужащих задержан задержали задержанных пытки пыток пытками исчезновение
насильственное правозащитник правозащитники журналист журналиста журналистов свобода свободы свободе
ёлка Ёлка ещё её объём подъезд съёмка Пётр Фёдор Семёнов Артёмовск Новая Каховка Новой Каховке Одессе
красивейший красивейшие лучшими постановление организованность организованности кошка кошки кошками бежать
бежавший бежавшись прыгавшие читавшая читаемый говорящий скажите делайте пейте рассказывали пройдёт
мирный мирных мирное большие большая сильнейшего государственный государственных""".split()

UK = """п'ять м'ясо пам'ять сім'я об'єкт з'їзд В'ячеслав м’ясо пам’ять ім’я сім’ї ґанок Ґрунт ґудзик їжак
Їжак їхати їжа ії є Євген Європа європейський українська українських українськими громадянин громадяни
громадянами війна війни війною військовий військові військових звільнення звільнили затримання катування
катувань зникнення насильницьке правозахисник правозахисники журналістка журналістки свобода свободи
обстріл обстріли обстрілами обстрілів знищено знищили знищення зруйновано повідомляє повідомили
навчаючись збираються дивлячись Кропивницький Житомир Чернігів Чорнобиль Ізмаїл Ізюм""".split()

ZH = """中国 新疆 维吾尔 西藏 香港 北京 上海 人权 理事会 特别报告员 任意拘留 酷刑 强迫失踪 言论自由 和平集会 政府
閣下 資訊 收到 關於 中華人民共和國 臺灣 𠀀 𠀁 𪚥 𩸽 日本語 東京 한국어 서울 대한민국 ひらがな カタカナ ﾊﾝｶｸ""".split()

MIXED = ["вagнер", "Bагнер", "kиев", "Kиeв", "москвa", "MOCKBA", "Мoсква", "прuвет", "cтpaнa", "ВАГНЕР", "Waгнер",
         "abcабв", "аbc", "xxxуууzzz", "Kyivкиев", "قصفab", "abقصف", "中文abc", "abc中文", "кит中", "αβγabc",
         "Ζeus", "Аpple", "раураl", "ЕХРО", "ехро", "сосо", "оооо", "ааа", "aaa", "aa", "Gooood", "nooooo", "соообщение",
         "WAAAAGNER", "11111", "1000", "a000b", "b0mb", "0bama", "10b", "b0", "0", "w@gner", "ca$h", "@user", "$5",
         "us$", "p@ss", "h@ck3r", "ш@хед", "р0сія", "м0сква", "b00m", "zer0", "C4$H", "B0MB", "Ш@ХЕД"]

SPACED = ["w a g n e r", "w-a-g-n-e-r", "w.a.g.n.e.r", "w_a_g_n_e_r", "w*a*g*n*e*r", "w·a·g·n·e·r", "w•a•g•n•e•r",
          "в а г н е р", "в-а-г-н-е-р", "a b c", "a b c d", "a-b-c-d", "a b-c d", "x.y.z.w", "1 2 3 4", "a b c d e f g",
          "I N F O", "к и е в", "u.s.a.", "u.s.a.f", "a. b. c. d.", "a  b  c  d", "aa b c d", "a b c dd", "_a_b_c_d_",
          "w a g n e r group", "the w a g n e r group"]

URLS = ["https://t.me/wagner_group/123", "http://example.com/a?b=c&d=0e", "www.Example.COM/path0", "t.me/Channel_N0",
        "@WagnerGroup", "@user_0ne", "write to info@ohchr.org now", "foo.bar+baz@mail.example.co.uk",
        "see https://ohchr.org/EN/HRBodies and @UN_HRC", "x@y", "a@b.c", "@", "@ @", "email:me@x.org,", "ca$h@x.com",
        "visit www.w@gner.com b0mb", "w@gner https://w@gner.com w@gner", "@w@gner", "https://", "http://x", "t.me/",
        "abc://def", "www.", "(https://example.org/x)", "«@handle»", "hello@", "user@@host.com", "@@double"]

PUNCT = ["", " ", "   ", "\t\n", "!!!", "...", "—", "–", "-", "--", "---", "'", "\"", "\"\"", "''", "’", "ʼ", "`", "«»",
         "¿qué?", "¡hola!", "(test)", "[x]", "{y}", "a/b", "a\\b", "a|b", "a&b", "a+b", "a=b", "a#b", "#hashtag", "%",
         "100%", "$100", "€5", "£", "¥", "©", "®", "°C", "1.5", "1,5", "1 000", "1_000", "_", "__", "a_b", "_a", "a_",
         "\u200b", "a\u200bb", "a\u200cb", "a\u200db", "a\xadb", "\ufeffabc", "a\u2060b", "\u200e\u200fabc",
         "á", "é", "ñ", "ñ", "Å", "Å", "Ǆ", "ǆ", "ﬀ", "\xa0", "a\xa0b", "a\u3000b",
         "a\x1cb", "a\x1fb", "a\x85b", "a\u2028b", "a\u2029b", "a\u1680b", "a\u202fb", "a\u205fb", "\u180e",
         "", "5", "xy", "ᴬᴮᶜ", "Ⓐⓑⓒ", "①②③", "⑴⑵", "㊀", "㍱", "ｆｕｌｌｗｉｄｔｈ", "ＡＢＣ１２３",
         "𝐁𝐨𝐥𝐝", "𝔉𝔯𝔞𝔨𝔱𝔲𝔯", "𝕕𝕠𝕦𝕓𝕝𝕖", "😀", "a😀b", "👍🏽", "🇺🇦", "x̧", "Σ", "ΣΣ", "ΑΣ", "ΑΣ ΑΣ", "ΑΣΑ", "Α.Σ",
         "ΑΣ.", "ΑΣ1", "1Σ", "aΣ", "aΣb", "ΌΣΟΣ", "ΘΕΟΣ ΚΑΙ", "ΣΑΣ'", "ΑΣ́", "İ", "İi", "Iİ", "i̇", "ı", "I",
         "ǰ", "ŉ", "ẞ", "ß", "ﬆ", "ΐ", "Ꭰ", "ꭰ", "Ω", "K", "Å", "ͅ", "Ⅷ", "ⅷ", "Ⓩ", "ʼn"]


# targeted edge words: astral code points inside Arabic/Cyrillic/Latin words (code-point vs UTF-16 lengths),
# non-ASCII decimal digits next to 0, letters that are Alphabetic but not \p{L}, short Ukrainian reflexives
ASTRAL = ["ال𠀀ب", "ال𠀀بب", "البب𠀀ات", "الببب𠀀ات", "بب𠀀ات", "و𠀀𠀀𠀀", "ب𠀀𠀀𠀀ها", "киев𠀀𠀀", "abc𠀀𠀀de", "𠀀𠀀𠀀𠀀",
          "kyiv𠀀", "ab𝐀𝐀cd", "абв𝟎", "w𠀀gner", "𠀀abc", "abc😀😀😀", "a𠀀a𠀀a𠀀"]
EDGE_WORDS = ["b0१", "१0b", "b0߁", "x0٣", "a0٣", "a0۳", "b0๑", "๑0b", "abcdↁ", "testᛮ", "ↁↁↁↁ", "wordⅯ", "kyivↂ",
              "дівся", "бився", "мився", "вчися", "їдься", "ївся", "сіся", "біжися", "ясність", "ґава", "єдність",
              "ΣΑΣ ΣΑΣ", "ΌΣΟΣ ΣΟΦΟΣ", "Σ1Σ", "ΑΣ-ΑΣ", "ΑΣ_ΑΣ", "ΑΣ\xadΒ", "ΑΣ\u200bΒ", "ΑΣ'Β", "aΣ.", "ΑΣͅ",
              "Kyiv́", "ёлка", "Ё", "й", "й", "ї", "ї"]


def variants_ar(w):
    out = [w, "ال" + w, "وال" + w, "بال" + w, "و" + w, "ب" + w, "ل" + w, "لل" + w, "ف" + w, "س" + w, "ك" + w,
           w + "ات", w + "ون", w + "ين", w + "ها", w + "هم", w + "ة", w + "ية", w + "ي", w + "ت", w + "وا"]
    return out


def variants_ru(stem):
    ends = ["", "а", "у", "ом", "е", "ы", "ов", "ами", "ах", "ий", "ая", "ое", "ые", "ого", "ому", "ыми", "ых",
            "ся", "ась", "ешь", "ет", "ут", "ли", "ла", "ть", "вший", "вшись", "ивши", "ость", "ейший", "нн", "ь",
            "ия", "иями", "ией", "ье"]
    return [stem + e for e in ends]


def variants_uk(stem):
    ends = ["", "а", "у", "ом", "і", "ів", "ами", "ях", "ий", "ої", "ою", "ого", "ому", "ими", "ться", "ються",
            "ати", "ють", "ла", "ли", "ь", "ює", "ює", "їв", "ся", "сь", "ього"]
    return [stem + e for e in ends]


def leet(w, rnd):
    tbl = {"a": "@", "s": "$", "o": "0"}
    return "".join(tbl[c] if c in tbl and rnd.random() < 0.6 else c for c in w)


def homoglyph(w, rnd):
    lat, cyr = "aeopcxykmtbhi", "аеорсхукмтвні"
    m = dict(zip(lat, cyr)) | dict(zip(cyr, lat))
    return "".join(m[c] if c in m and rnd.random() < 0.3 else c for c in w)


def add_tashkeel(w, rnd):
    marks = "ًٌٍَُِّْٰـ"
    return "".join(c + (rnd.choice(marks) if rnd.random() < 0.5 else "") for c in w)


# Arabic/Persian personal names in Latin and Cyrillic spellings (KEY_VERSION 3 name folds), plus near misses
NAMES_AR = """Mohamed Muhammad Mohammed Mohammad Muhammed Mohamad Mouhamed Mhamed Mohamud Mahmoud Mahmud Magomed Mehmet Hamid Hamed
Hamad Ahmed Ahmad Akhmed Hussein Husayn Hossein Husein Hussain Houssein Husain Hassan Hasan Husni Youssef Yusuf Yousef
Yousif Youssouf Iosif Yosef Joseph Khaled Khalid Abd Abdel Abdul Abdal Abdil Abdol Abdoul Abdur Abdus Abdi Abdou Abdu
Abdulrahman Abdelrahman Abdurrahman Abdirahman Abdallah Abdullah Abdulla Abdellah Abdelaziz Abdulaziz Abdussalam
Abdunnasir Abdulkarim Abdukarim abduction abducted abdomen abdominal abdicate abdiquer abducción Abdera
Мухаммед Мохаммед Мухаммад Ахмед Ахмад Хусейн Хусайн Юсуф Иосиф Абдулла Абдуллах Абдель Абдул Абдурахман абдукция""".split()
NAMES_AR_MULTI = ["Abdel Rahman", "Abd al-Rahman", "Abdul Rahman", "Abd el Rahman", "Abd ar-Rahman", "Abd Allah",
                  "Abd al-Aziz", "Abd as-Salam", "Abd ad-Dayem", "Abd al Lah", "Abdul", "Mohamed Abdul", "Abd",
                  "Al-Masri", "El Masri", "Masri", "Mohamed El-Masri", "Mohammed al Masri", "Muhammad ul-Masri",
                  "Mohamed Masri", "Zia ul Haq", "Zia-ul-Haq", "Абд аль-Рахман", "Абд эль Азиз", "Мухаммед аль-Масри",
                  "Мухаммед эль Масри", "Ahmed Abdel Aziz Hussein", "Yousef Abd Allah", "Wadi el Ku", "Wadi al Ku",
                  "Abd er Rahman", "Kul Abd el Ali", "Ed Wad Abd Alla", "abd el", "abd al", "el abd", "x al y", "al al"]


def repo_seed():
    """Names from this repository's own lexicons and curated place lists (no external text)."""
    words, names = set(), []
    for f in sorted((DATA / "lexicon").glob("*.json")) + sorted((DATA / "gazetteer" / "curated").glob("*.json")):
        for e in json.loads(f.read_text("utf-8")):
            for k, v in e.items():
                if k in ("id", "label", "category", "type", "admin1", "lat", "lon", "confidence", "notes", "country",
                         "reason"):
                    continue
                for n in ([v] if isinstance(v, str) else v if isinstance(v, list) else []):
                    if isinstance(n, str) and n:
                        names.append(n)
                        words.update(re.findall(r"\S+", n))
    return sorted(words), list(dict.fromkeys(names))


def build_inputs():
    rnd = random.Random(20261123)
    base = EN + FR + ES + PT + TR + DE_MISC + AR + AR_TASHKEEL + FA + DIGITS + RU + UK + ZH + MIXED
    words = list(base)
    words += [w.upper() for w in EN + FR + ES + PT + TR + RU + UK]
    words += [w.capitalize() for w in EN + FR + ES + PT + TR + RU + UK]
    ar_bases = ["مدرس", "قصف", "خرطوم", "فاشر", "جنين", "سيار", "مستشفى", "كتاب", "طائر", "مدين", "حرب", "شهيد", "سلام"]
    for b in ar_bases:
        words += variants_ar(b)
    words += [add_tashkeel(w, rnd) for w in AR[:60]]
    for s in ["обстрел", "журналист", "задерж", "красив", "организованн", "беспилотник", "москв", "прыга", "чита",
              "говор", "государствен", "киев", "бахмут", "уда", "пытк", "свобод", "мир"]:
        words += variants_ru(s)
    for s in ["обстріл", "журналіст", "затриман", "катуван", "громадян", "військов", "звільн", "свобод", "україн",
              "знищ", "повідомл", "їжак", "європ"]:
        words += variants_uk(s)
    words += [leet(w, rnd) for w in EN[:200]]
    words += [homoglyph(w, rnd) for w in EN[:150] + RU[:120]]
    words += ["".join(c * 3 if rnd.random() < 0.2 else c for c in w) for w in EN[:80] + RU[:60]]
    words += NAMES_AR + [w.upper() for w in NAMES_AR] + [w.lower() for w in NAMES_AR]
    seed_words, seed_names = repo_seed()
    words += seed_words
    words = list(dict.fromkeys(words))

    texts = list(dict.fromkeys(SPACED + URLS + PUNCT + MIXED + DIGITS + ASTRAL + EDGE_WORDS))
    for _ in range(600):
        texts.append(" ".join(rnd.choice(words) for _ in range(rnd.randint(2, 8))))
    texts += [" ".join(rnd.choice(AR + FA) for _ in range(5)) for _ in range(60)]
    texts += [" ".join(rnd.choice(RU + UK) for _ in range(5)) for _ in range(60)]
    texts += [rnd.choice(EN) + rnd.choice(["'", "’", "ʼ", "`", "-", "_", ".", ""]) + rnd.choice(EN) for _ in range(80)]
    texts += NAMES_AR_MULTI
    texts += [" ".join(rnd.choice(NAMES_AR + NAMES_AR_MULTI) for _ in range(rnd.randint(2, 4))) for _ in range(150)]
    texts = list(dict.fromkeys(texts))

    queries = []
    queries += words
    queries += texts
    queries += sorted(lexicon.STOPWORDS)
    queries += [w.upper() for w in sorted(lexicon.STOPWORDS)[:60]]
    syntax = [
        "", " ", "OR", "or", "Or", "NEAR", "near", "NEAR/5", "-", "--", "-x", "- x", '"', '""', '" "', '"a"', '"a"*', '"a b"*',
        'a OR b', 'a or b', 'a OR', 'OR a', 'a OR OR b', 'a -b', '-a b', '-a', '-a -b', 'a -b OR c', 'a OR -b',
        '"human rights" council', '"human rights"* -council', '"права человека" Киев', '"الدعم السريع" الخرطوم',
        'kyiv NEAR/5 kharkiv', 'kyiv NEAR kharkiv', 'kyiv NEAR/0 kharkiv', 'kyiv NEAR/9999 kharkiv',
        'kyiv NEAR/10000 kharkiv', 'kyiv NEAR/12 "human rights"', '"human rights" NEAR/3 torture',
        '"human rights"* NEAR/3 torture', 'a NEAR/3 b NEAR/7 c', 'a NEAR b NEAR c NEAR d', 'a NEAR -b', '-a NEAR b',
        'a NEAR OR b', 'NEAR a', 'a NEAR', 'a NEAR NEAR b', '"NEAR" a', 'a "NEAR/5" b', 'near/5', 'Near/5 x',
        'обстрел NEAR/5 Бахмут', 'обстрелом NEAR Бахмуте', 'الخرطوم NEAR/5 قصف', 'والسيارات NEAR/2 والمدارس NEAR/2 بالمستشفيات',
        'والسيارات NEAR والمدارس NEAR بالمستشفيات NEAR للطائرات', 'kyiv NEAR kharkiv NEAR odesa NEAR mariupol NEAR donetsk',
        'wagner NEAR legion NEAR akhmat', 'foo-bar NEAR baz', 'rock-n-roll NEAR/4 music', "o'brien NEAR smith",
        'w a g n e r NEAR bakhmut', 'w@gner OR вагнер', '-w@gner b0mb', '"w a g n e r"', '"вagнер" группа',
        'https://t.me/wagner NEAR bakhmut', '@WagnerGroup OR "Wagner Group"', 'info@ohchr.org',
        'kyiv OR kiev OR київ OR киев', '(kyiv)', 'kyiv*', '"kyiv"*', 'kyiv"', '"kyiv', 'a"b c"d', '"a" "b"', '""a""',
        'NEAR/5 a b', 'a NEAR/5', 'a NEAR/x b', 'a NEAR/-1 b', 'a NEAR/ b', 'a NEAR/1.5 b', 'a NEAR/٥ b',
        'a\ufeffb', 'a\x1cb c', 'a\u0085b', '\ufeffNEAR', 'a \ufeffOR b', 'a\u3000OR\u3000b', 'a\xa0OR\xa0b',
        'ΣΟΦΟΣ', 'ΟΔΟΣ ΣΟΦΟΣ', 'İstanbul OR ıstanbul', 'straße OR strasse', 'ǅemal', '中国 人权', '中国NEAR人权',
        '中国 NEAR/2 人权', 'x' * 300, " ".join(["kyiv"] * 30), " ".join(f"word{i}" for i in range(50)),
        " ".join(EN[:130]), " ".join(EN[:150]) + " NEAR kyiv", "a " * 200,
        "мариуполь донецк " * 10, "تهران ایران " * 10, "سيذهبون OR فالحرب -وسيقول",
        "a OR NEAR b", "x OR NEAR/5 y", "OR NEAR z", "a -b NEAR c", "a OR NEAR -b", '"x y" OR NEAR/2 z',
        "والسيارات NEAR kyiv NEAR kharkiv NEAR odesa", "والسيارات NEAR/4 kyiv NEAR kharkiv NEAR odesa NEAR mariupol",
        "والسيارات NEAR والمدارس NEAR kyiv NEAR kharkiv", "kyiv NEAR kharkiv NEAR odesa NEAR mariupol",
        "Бахмуте NEAR والسيارات NEAR kyiv NEAR kharkiv NEAR odesa", "kyiv NEAR والسيارات NEAR odesa NEAR والمدارس",
    ]
    queries += ASTRAL + EDGE_WORDS
    queries += syntax
    for _ in range(500):
        n = rnd.randint(1, 6)
        toks = []
        for i in range(n):
            w = rnd.choice(words)
            r = rnd.random()
            if r < 0.08:
                w = "-" + w
            elif r < 0.14:
                w = '"' + w + " " + rnd.choice(words) + '"' + ("*" if rnd.random() < 0.3 else "")
            toks.append(w)
            if i < n - 1:
                r = rnd.random()
                if r < 0.12:
                    toks.append("OR")
                elif r < 0.22:
                    toks.append(rnd.choice(["NEAR", "NEAR/5", "NEAR/1", "NEAR/30", "NEAR/0"]))
        queries.append(" ".join(toks))
    queries = list(dict.fromkeys(queries))

    names = list(dict.fromkeys(words + texts + ASTRAL + EDGE_WORDS + [
        "El Fasher", "Al-Fashir", "al Fashir", "Alfashir", "El Geneina", "ad Damazin", "ash Shajara", "Ar Rahad",
        "Umm Durman", "Kyiv", "Kiev", "Київ", "Киев", "Artyomovsk", "Artemivsk", "Артемовск", "Mykolayiv", "Nikolayev",
        "Миколаїв", "Николаев", "Kharkiv", "Харків", "Yalta", "Yasinuvata", "Novaya Kakhovka", "Nova Kakhovka",
        "Нова Каховка", "Новая Каховка", "الفاشر", "والفاشر", "الجنينة", "بالخرطوم", "ال", "al", "el", "al al", "el-",
        "Al", "AL Qasr", "Ed Damer", "Es Suki", "Ez Zeidab", "Ul Bator", "Ash", "ash", "Adh Dhahiriya",
        "O'Hare", "D’Arcy", "Ma`arrat al-Nu`man", "Ma‘arrat an-Nu‘man", "Ḥalab", "Ṣanʿāʾ", "Dimashq", "Ḥimṣ",
        "Shchyolkovo", "Щёлково", "Tchernobyl", "Schastia", "Щастя", "Zhytomyr", "Kropyvnytskyi", "Xinjiang",
        "Phnom Penh", "Ouagadougou", "Joseph", "Djibouti", "Yokohama", "Yoshkar-Ola", "Йошкар-Ола", "Hryhoriy",
        "Huliaipole", "Гуляйполе", "Kherson", "Херсон", "Qatar", "Iraq", "Xai-Xai", "Wagner", "Вагнер", "Vagner"]
        + NAMES_AR_MULTI + seed_names))
    return words, texts, queries, names


# --------------------------------------------------------------------------- #
# Code-point sweep
# --------------------------------------------------------------------------- #

def codepoints():
    cps = []
    for c in range(0x110000):
        if 0xD800 <= c <= 0xDFFF or unicodedata.category(chr(c)) in ("Cn", "Cs", "Co"):
            continue
        if 0x3400 <= c <= 0x9FFF or 0xAC00 <= c <= 0xD7A3 or 0x20000 <= c <= 0x3FFFF:
            if c % 97:
                continue                                 # CJK / Hangul bulk: sample
        elif c >= 0x10000 and c % 7 and not (0x1D400 <= c <= 0x1D7FF or 0x1F100 <= c <= 0x1F1FF):
            continue                                     # other astral: sample (math alnum, enclosed: all)
        cps.append(c)
    return cps


def constants():
    """lps tables the JS port retypes by hand: compared one-to-one by the test, so a mistyped entry fails."""
    bmp = lambda rx: [c for c in range(0x10000) if not 0xD800 <= c <= 0xDFFF and rx.search(chr(c))]
    return {
        "AR_PREFIXES": list(textnorm._AR_PREFIXES), "AR_SUFFIXES": list(translit._AR_SUFFIXES),
        "AR_ARTICLE": list(translit._AR_ARTICLE),
        "RU_VOW": translit._RU_VOW, "RU_PERF1": list(translit._RU_PERF1), "RU_PERF2": list(translit._RU_PERF2),
        "RU_ADJ": list(translit._RU_ADJ), "RU_PART1": list(translit._RU_PART1), "RU_PART2": list(translit._RU_PART2),
        "RU_VERB1": list(translit._RU_VERB1), "RU_VERB2": list(translit._RU_VERB2), "RU_NOUN": list(translit._RU_NOUN),
        "UK_ENDINGS": list(translit._UK_ENDINGS),
        "CY": dict(translit._CY), "LAT_MULTI": [list(x) for x in translit._LAT_MULTI], "LAT_ONE": dict(translit._LAT_ONE),
        "LAT_ARTICLE": sorted(translit._LAT_ARTICLE), "LAT_TWINS": textnorm._LAT_TWINS, "CYR_TWINS": textnorm._CYR_TWINS,
        "TRANS": {chr(k): (v or "") for k, v in sorted(textnorm._TRANS.items())},
        "STOPWORDS": sorted(lexicon.STOPWORDS),
        "LAT_SUFFIXES": [list(x) for x in textnorm._LAT_SUFFIXES], "MIN_LAT_WORD": textnorm.MIN_LAT_WORD,
        "MIN_LAT_STEM": textnorm.MIN_LAT_STEM, "LAT_WORD": textnorm._LAT_WORD.pattern,
        "NAME_FOLDS": [[rx.pattern, c] for rx, c in translit._NAME_FOLDS], "ABD_WORDS": sorted(translit._ABD_WORDS),
        "ABD_ALLAH": translit._ABD_ALLAH.pattern, "ABD_JOINED": translit._ABD_JOINED.pattern,
        "ALLAH": translit._ALLAH.pattern, "NAME_ARTICLES": sorted(translit._NAME_ARTICLES),
        "CY_ARTICLE": sorted(translit._CY_ARTICLE),
        "MAX_NEAR": lexicon.MAX_NEAR, "MAX_ALTS_TOTAL": lexicon.MAX_ALTS_TOTAL, "DEFAULT_NEAR": textnorm.DEFAULT_NEAR,
        "NO_DICT_STATUS": lexicon.dict_status(None),
        "chars": {"AR_MARKS": bmp(textnorm._AR_MARKS), "APOS": bmp(translit._APOS), "SEPS": bmp(textnorm._SEPS),
                  "UK_LETTERS": bmp(translit._UK_LETTERS), "ARABIC": bmp(translit._ARABIC),
                  "CYRILLIC": bmp(translit._CYRILLIC), "LATIN": bmp(translit._LATIN)},
    }


def safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:                             # recorded so the JS port must fail the same way
        return {"error": type(e).__name__}


def main():
    if "--tables" in sys.argv:
        for k, v in unicode_tables().items():
            print(f'  {k}: "{v}",')
        return
    assert lexicon.get_dict() is None, "a dictionary.db is configured: golden vectors must be built without one"
    words, texts, queries, names = build_inputs()
    exp_opts = [{}] * len(queries)
    extra = [
        ("kyiv bakhmut", {"enabled": False}), ("", {"enabled": False}),
        ("kyiv bakhmut", {"skip": "kyiv"}), ("kyiv bakhmut", {"skip": ["bakhmut", " "]}),
        ("kyiv bakhmut", {"drop": "Cyrillic ≈ kiv"}), ("kyiv bakhmut", {"drop": ["CYRILLIC ≈ BAQMUT", ""]}),
        ("kyiv NEAR bakhmut", {"skip": "kyiv"}), ("kyiv NEAR bakhmut", {"drop": "cyrillic ≈ baqmut"}),
        ("kyiv NEAR bakhmut", {"drop": "+cyrillic ≈ baqmut"}), ("legion wagner", {"skip": "Legion,Wagner"}),
        ("kyiv bakhmut", {"skip": "kyiv\x1c"}), ("kyiv bakhmut", {"skip": "\x85kyiv"}),
        ("kyiv bakhmut", {"drop": "cyrillic ≈ kiv\x1f,\ufeff"}), ("kyiv bakhmut", {"skip": ["\x1d", "bakhmut\u3000"]}),
    ]
    norm_v = [[t, safe(textnorm.normalize, t)] for t in list(dict.fromkeys(words + texts + names))]
    mk_v = [[n, safe(translit.match_key, n)] for n in names]
    fq_v = [[q, safe(textnorm.fts_query, q)] for q in queries]
    sc_v = []
    for q, e in fq_v[::7]:
        if isinstance(e, str):
            for tx, nm in ((True, False), (False, True), (True, True), (False, False)):
                sc_v.append([e, tx, nm, textnorm.fts_scoped(e, tx, nm)])
    ex_v = [[q, o, safe(lexicon.expand, q, None, None, *([o.get("enabled", True), o.get("drop", ()), o.get("skip", ())]))]
            for q, o in list(zip(queries, exp_opts)) + extra]
    cp_v = []
    for c in codepoints():
        ch = chr(c)
        cp_v.append([c, textnorm.normalize(ch), translit.match_key("ab" + ch + "cd"),
                     textnorm.fts_query("ab" + ch + "cd")])
    golden = {
        "meta": {"KEY_VERSION": translit.KEY_VERSION, "FTS_VERSION": index.FTS_VERSION,
                 "ROMAN_PREFIX": translit.ROMAN_PREFIX, "unidata_version": unicodedata.unidata_version,
                 "python": sys.version.split()[0]},
        "tables": unicode_tables(), "constants": constants(),
        "normalize": norm_v, "match_key": mk_v, "fts_query": fq_v, "fts_scoped": sc_v, "expand": ex_v,
        "codepoints": cp_v,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(golden, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    n = sum(len(golden[k]) for k in ("normalize", "match_key", "fts_query", "fts_scoped", "expand", "codepoints"))
    print(f"wrote {OUT.relative_to(ROOT)}: {n} vectors "
          + ", ".join(f"{k}={len(golden[k])}" for k in ("normalize", "match_key", "fts_query", "fts_scoped", "expand", "codepoints")))


if __name__ == "__main__":
    main()
