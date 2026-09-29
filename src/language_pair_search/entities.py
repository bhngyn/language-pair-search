"""
Pattern entities: phone numbers, crypto addresses, bank cards, Russian/Ukrainian unit numbers, callsigns and
vehicle plates found in the TEXT of posts, comments and OCR/speech text.

These are CLAIMS IN TEXT to check, not findings: a string that looks like a phone number may be an ID, a
made-up number or an old post. Precision beats recall here, so ambiguous shapes are skipped.

extract(text) -> [{"kind", "value" (canonical), "raw" (as written), "start", "end", "meta"}]
  phone     +CC national (E.164), country in meta; also wa.me links; Russian 8-format only next to a phone word
  btc       base58check (1..., 3...) and bech32/bech32m (bc1...), checksum validated
  eth       0x + 40 hex (EIP-55 mixed-case checksum is not checked: needs keccak, not in the stdlib)
  trx       T + 33 base58, checksum validated
  card      13-19 digits, Luhn-valid, known issuer prefix. value = first6…last4 (masked); the full number
            exists only in `raw`: callers should not log or display it
  unit      в/ч 12345, войсковая часть 12345, військова частина А1234
  callsign  позывной «X» / позывной X / п-ной X / (позывной X)
  plate     Russian (А123ВС77, Cyrillic letter classes АВЕКМНОРСТУХ + region) and Ukrainian (АА1234ВВ)
Latin look-alike letters typed in place of the Cyrillic ones are accepted and canonicalised.
"""

import hashlib
import re


VERSION = "1"        # bump when extract() changes: callers that store results should re-extract

KINDS = ("phone", "btc", "eth", "trx", "card", "unit", "callsign", "plate")
PRIORITY = {"card": 0, "btc": 1, "eth": 1, "trx": 1, "phone": 2, "unit": 3, "plate": 4, "callsign": 5}

# --------------------------------------------------------------------------- #
# Phone numbers
# --------------------------------------------------------------------------- #

# calling code -> (country, allowed national-number lengths). Unknown codes are not matched at all.
CC = {
    "1": ("US/CA", (10,)), "7": ("RU/KZ", (10,)), "20": ("EG", (9, 10)), "27": ("ZA", (9,)),
    "31": ("NL", (9,)), "32": ("BE", (8, 9)), "33": ("FR", (9,)), "34": ("ES", (9,)), "39": ("IT", (9, 10, 11)),
    "40": ("RO", (9,)), "44": ("GB", (10,)), "46": ("SE", (7, 8, 9, 10)), "47": ("NO", (8,)),
    "48": ("PL", (9,)), "49": ("DE", (10, 11)), "86": ("CN", (11,)), "90": ("TR", (10,)), "91": ("IN", (10,)),
    "92": ("PK", (10,)), "98": ("IR", (10,)),
    "211": ("SS", (9,)), "212": ("MA", (9,)), "213": ("DZ", (9,)), "216": ("TN", (8,)), "218": ("LY", (9,)),
    "221": ("SN", (9,)), "222": ("MR", (8,)), "223": ("ML", (8,)), "225": ("CI", (8, 10)), "227": ("NE", (8,)),
    "233": ("GH", (9,)), "234": ("NG", (10,)), "235": ("TD", (8,)), "236": ("CF", (8,)), "237": ("CM", (9,)),
    "242": ("CG", (9,)), "243": ("CD", (9,)), "249": ("SD", (9,)), "250": ("RW", (9,)), "251": ("ET", (9,)),
    "252": ("SO", (7, 8, 9)), "253": ("DJ", (8,)), "254": ("KE", (9,)), "255": ("TZ", (9,)), "256": ("UG", (9,)),
    "257": ("BI", (8,)), "258": ("MZ", (9,)), "260": ("ZM", (9,)), "263": ("ZW", (9,)), "291": ("ER", (7,)),
    "358": ("FI", (9, 10)), "359": ("BG", (8, 9)), "370": ("LT", (8,)), "371": ("LV", (8,)), "372": ("EE", (7, 8)),
    "373": ("MD", (8,)), "374": ("AM", (8,)), "375": ("BY", (9,)), "380": ("UA", (9,)), "381": ("RS", (8, 9)),
    "420": ("CZ", (9,)), "421": ("SK", (9,)), "961": ("LB", (7, 8)), "962": ("JO", (8, 9)), "963": ("SY", (8, 9)),
    "964": ("IQ", (9, 10)), "965": ("KW", (8,)), "966": ("SA", (8, 9)), "967": ("YE", (9,)), "968": ("OM", (8,)),
    "971": ("AE", (8, 9)), "972": ("IL", (8, 9)), "973": ("BH", (8,)), "974": ("QA", (8,)), "992": ("TJ", (9,)),
    "993": ("TM", (8,)), "994": ("AZ", (9,)), "995": ("GE", (9,)), "996": ("KG", (9,)), "998": ("UZ", (9,)),
}

_DIGITS = str.maketrans({**{chr(0x660 + i): str(i) for i in range(10)}, **{chr(0x6f0 + i): str(i) for i in range(10)},
                                 "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u2011": "-"})
# +CC then digit groups joined by space . - ( ) ; the whole run is 8-15 digits
_PHONE_PLUS = re.compile(r"(?<![\w+])(?:\+|00(?=[1-9]))[ ]?((?:\(?\d\)?[ .\-]?){8,15}\d)(?![\w])")
_PHONE_WA = re.compile(r"(?i)(?:wa\.me/|whatsapp\.com/send\?phone=|t\.me/\+)(\d{9,15})(?!\d)")
_PHONE_RU = re.compile(r"(?<![\w+])([78])[ \-]?\(?(9\d\d)\)?[ \-]?(\d{3})[ \-]?(\d{2})[ \-]?(\d{2})(?![\w])")
_PHONE_WORD = re.compile(r"(?i)(тел|phone|whats?app|ватсап|вотсап|вайбер|viber|звон|mob\b|هاتف|واتس|رقم|اتصل|جوال|تلفون)")


def _cc_split(digits):
    for n in (1, 2, 3):
        cc = digits[:n]
        if cc in CC and len(digits) - n in CC[cc][1]:
            # +7 is Russia/Kazakhstan (mobile/landline 3xx-9xx); 1 must be followed by 2-9
            if cc in ("1", "7") and digits[n] in "01":
                return None
            return cc, CC[cc][0]
    return None


def _phones(t):
    out = []
    for m in _PHONE_PLUS.finditer(t):
        digits = re.sub(r"\D", "", m.group(1))
        got = _cc_split(digits)
        if not got or len(set(digits)) < 3:
            continue
        out.append({"kind": "phone", "value": "+" + digits, "raw": m.group(0), "start": m.start(), "end": m.end(),
                    "meta": {"country": got[1], "cc": got[0]}})
    for m in _PHONE_WA.finditer(t):
        digits = m.group(1)
        got = _cc_split(digits)
        if got:
            out.append({"kind": "phone", "value": "+" + digits, "raw": m.group(0), "start": m.start(),
                        "end": m.end(), "meta": {"country": got[1], "cc": got[0], "via": "link"}})
    for m in _PHONE_RU.finditer(t):                    # 8 (9xx) xxx-xx-xx: only near a word that says "phone",
        before = t[max(0, m.start() - 60):m.start()]   # or in a list of numbers that already had one
        if not (_PHONE_WORD.search(before) or (out and out[-1]["end"] >= m.start() - 6 and out[-1]["kind"] == "phone")):
            continue
        out.append({"kind": "phone", "value": "+7" + m.group(2) + m.group(3) + m.group(4) + m.group(5),
                    "raw": m.group(0), "start": m.start(), "end": m.end(),
                    "meta": {"country": "RU/KZ", "cc": "7", "domestic": True}})
    return out


# --------------------------------------------------------------------------- #
# Crypto addresses
# --------------------------------------------------------------------------- #

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_IDX = {c: i for i, c in enumerate(_B58)}
_BECH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _b58check(s):
    """Decoded 21-byte payload (version byte + hash) if s is a valid 25-byte base58check string, else None."""
    n = 0
    for c in s:
        if c not in _B58_IDX:
            return None
        n = n * 58 + _B58_IDX[c]
    if n >> 200:
        return None
    raw = n.to_bytes(25, "big")
    if len(s) - len(s.lstrip("1")) != len(raw) - len(raw.lstrip(b"\0")):
        return None                                     # leading 1s must match the leading zero bytes
    chk = hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4]
    return raw[:21] if chk == raw[21:] else None


def _bech32_polymod(values):
    gen = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (b >> i) & 1 else 0
    return chk


def _bech32_ok(s):
    if s.lower() != s and s.upper() != s:
        return False
    s = s.lower()
    pos = s.rfind("1")
    hrp, data = s[:pos], s[pos + 1:]
    if hrp != "bc" or len(data) < 7 or any(c not in _BECH for c in data):
        return False
    vals = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + [_BECH.index(c) for c in data]
    return _bech32_polymod(vals) in (1, 0x2bc830a3)    # bech32, bech32m


_BTC_B58 = re.compile(r"(?<![\w])[13][1-9A-HJ-NP-Za-km-z]{25,34}(?![\w])")
_BTC_BECH = re.compile(r"(?<![\w])(?:bc1|BC1)[0-9A-Za-z]{11,71}(?![\w])")
_ETH = re.compile(r"(?<![\w])0x[0-9a-fA-F]{40}(?![\w])")
_TRX = re.compile(r"(?<![\w])T[1-9A-HJ-NP-Za-km-z]{33}(?![\w])")


def _crypto(t):
    out = []
    for m in _BTC_B58.finditer(t):
        p = _b58check(m.group(0))
        if p is not None and p[0] in (0x00, 0x05):
            out.append({"kind": "btc", "value": m.group(0), "raw": m.group(0), "start": m.start(), "end": m.end(),
                        "meta": {"format": "p2pkh" if p[0] == 0 else "p2sh"}})
    for m in _BTC_BECH.finditer(t):
        if _bech32_ok(m.group(0)):
            out.append({"kind": "btc", "value": m.group(0).lower(), "raw": m.group(0), "start": m.start(),
                        "end": m.end(), "meta": {"format": "bech32"}})
    for m in _ETH.finditer(t):
        h = m.group(0)[2:].lower()
        if len(set(h)) > 3:                             # 0x000…0 and 0xffff…f are placeholders, not addresses
            out.append({"kind": "eth", "value": "0x" + h, "raw": m.group(0), "start": m.start(), "end": m.end(),
                        "meta": {}})
    for m in _TRX.finditer(t):
        p = _b58check(m.group(0))
        if p is not None and p[0] == 0x41:
            out.append({"kind": "trx", "value": m.group(0), "raw": m.group(0), "start": m.start(), "end": m.end(),
                        "meta": {}})
    return out


# --------------------------------------------------------------------------- #
# Bank cards
# --------------------------------------------------------------------------- #

_CARD = re.compile(r"(?<![\w+.,/\-])(\d{4}(?:[ \-]\d{4}){3}|\d{4}[ \-]\d{6}[ \-]\d{4,5}|\d{13,19})(?![\w]|[.,]\d)")
_CARD_TAIL = re.compile(r"[ \-](\d{1,3})(?![\w]|[.,]\d)")


def luhn(digits):
    s = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            d -= 9 if d > 9 else 0
        s += d
    return s % 10 == 0


def _brand(d):
    n = len(d)
    if d[0] == "4" and n in (13, 16, 19):
        return "visa"
    if (d[:2] in ("51", "52", "53", "54", "55") or "2221" <= d[:4] <= "2720") and n == 16:
        return "mastercard"
    if "2200" <= d[:4] <= "2204" and n in (16, 17, 18, 19):
        return "mir"
    if d[:2] in ("34", "37") and n == 15:
        return "amex"
    if d[:2] == "62" and 16 <= n <= 19:
        return "unionpay"
    if "3528" <= d[:4] <= "3589" and 16 <= n <= 19:
        return "jcb"
    if (d[:4] == "6011" or d[:2] == "65" or "644" <= d[:3] <= "649") and 16 <= n <= 19:
        return "discover"
    if d[:4] in ("8600", "9860") and n == 16:
        return "uzcard/humo"
    if (d[:2] in ("50", "56", "57", "58") or d[:1] == "6") and 12 <= n <= 19:
        return "maestro"
    if (d[:3] in ("300", "301", "302", "303", "304", "305") or d[:2] in ("36", "38")) and 14 <= n <= 19:
        return "diners"
    return None


def _cards(t):
    out = []
    for m in _CARD.finditer(t):
        cands = [(m.group(1), m.end())]
        tail = _CARD_TAIL.match(t, m.end())              # 19-digit cards are written 4-4-4-4-3
        if tail and re.fullmatch(r"\d{4}([ \-]\d{4}){3}", m.group(1)):
            cands.insert(0, (m.group(1) + t[m.end():tail.end()], tail.end()))
        for raw, end in cands:
            d = re.sub(r"\D", "", raw)
            if not 13 <= len(d) <= 19 or not luhn(d) or len(set(d)) < 4:
                continue
            brand = _brand(d)
            if not brand or (raw.isdigit() and len(d) in (13, 14)):
                continue                                # bare 13/14 digits: timestamps and ids, far too common
            out.append({"kind": "card", "value": f"{d[:6]}…{d[-4:]}", "raw": raw, "start": m.start(), "end": end,
                        "meta": {"brand": brand, "digits": len(d), "masked": True}})
            break
    return out


# --------------------------------------------------------------------------- #
# Military units, callsigns, plates
# --------------------------------------------------------------------------- #

_UNIT = re.compile(r"(?i)(?<![\w])(в\s?[/\\]\s?ч|в[.\-]\s?ч\.?|в\.\s?ч|в/ч|войсков\w*\s+част\w*|військов\w*\s+частин\w*)"
                   r"\s*(?:№|N|no\.?|номер)?\s*([АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЮЯA-Z]?\s?\d{4,5})(?!\d)")


def _units(t):
    out = []
    for m in _UNIT.finditer(t):
        num = re.sub(r"\s", "", m.group(2)).upper()
        if not re.fullmatch(r"[^\d]?\d{4,5}", num):
            continue
        out.append({"kind": "unit", "value": num, "raw": m.group(0), "start": m.start(), "end": m.end(),
                    "meta": {"form": re.sub(r"\s+", " ", m.group(1)).lower()}})
    return out


_CALL_WORD = r"(?:позывн(?:ой|ым|ого|ому|ом|ые|ых)|п-ной|п-ным|позыв\.)"
_CALL = re.compile(
    rf"(?i)(?<![\w]){_CALL_WORD}\s*[:\-–—]?\s*(?:[«\"„“'‘]\s*([^»\"”“'’\n,;]{{2,30}}?)\s*[»\"”“'’]|"
    rf"(?-i:([А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9_\-]{{2,20}})))")
_CALL_STOP = {"не", "его", "это", "был", "как", "так", "что", "она", "они", "там", "тот", "для", "при", "или",
              "уже", "ещё", "еще", "его", "мой", "твой", "наш", "ваш", "все", "всё", "кто", "где", "оно",
              "the", "and", "not", "was", "for"}


def _callsigns(t):
    out = []
    for m in _CALL.finditer(t):
        name = (m.group(1) or m.group(2) or "").strip()
        val = re.sub(r"\s+", " ", name).casefold()
        if len(val) < 2 or val in _CALL_STOP or val.isdigit():
            continue
        out.append({"kind": "callsign", "value": val, "raw": m.group(0), "start": m.start(), "end": m.end(),
                    "meta": {"display": re.sub(r"\s+", " ", name), "quoted": bool(m.group(1))}})
    return out


# Russian plates use the 12 letters that exist in both alphabets; Latin look-alikes are folded to Cyrillic.
_RU_L = "АВЕКМНОРСТУХ"
_LAT2CYR = str.maketrans("ABEKMHOPCTYXabekmhopctyx", "АВЕКМНОРСТУХАВЕКМНОРСТУХ")
_RU_RE = "[АВЕКМНОРСТУХABEKMHOPCTYX]"
_PLATE_RU = re.compile(rf"(?<![\w])({_RU_RE})[ \-]?(\d{{3}})[ \-]?({_RU_RE}{{2}})[ \-]?(\d{{2,3}})(?:[ ]?(?:RUS|rus|Rus))?(?![\w])")
_RU_REGIONS = {f"{i:02d}" for i in range(1, 100)} | {"102", "113", "116", "121", "123", "124", "125", "126", "134",
                                                    "136", "138", "142", "150", "152", "154", "159", "161", "163",
                                                    "164", "173", "174", "177", "178", "186", "190", "196", "197",
                                                    "198", "199", "702", "716", "750", "761", "763", "777", "790",
                                                    "797", "799"}
# Ukrainian: two-letter region series + 4 digits + two letters, letters from АВСЕНІКМОРТХ (Latin forms kept)
_UA_L = "ABCEHIKMOPTX"
_UA2LAT = str.maketrans("АВСЕНІКМОРТХавсенікмортх", "ABCEHIKMOPTXABCEHIKMOPTX")
_UA_RE = "[АВСЕНІКМОРТХABCEHIKMOPTX]"
_PLATE_UA = re.compile(rf"(?<![\w])({_UA_RE}{{2}})[ \-]?(\d{{4}})[ \-]?({_UA_RE}{{2}})(?![\w])")
_UA_SERIES = set("AA KA TA YA AB KB AC KC AE KE AH KH AM KM AO KO AP KP AT KT AI KI BA HA BB HB BC HC BE HE BH HH "
                 "BI HI BK HK BM HM BO HO AX KX BT HT BX HX CA IA CB IB CE IE AK KK CH IH".split())


def _plates(t):
    out = []
    for m in _PLATE_RU.finditer(t):
        a, num, bc, reg = m.groups()
        if num == "000" or reg not in _RU_REGIONS:
            continue
        # skip when it is really an Ukrainian-shaped series (two letters first): not the RU shape anyway
        val = (a + num + bc).translate(_LAT2CYR).upper() + reg
        out.append({"kind": "plate", "value": val, "raw": m.group(0), "start": m.start(), "end": m.end(),
                    "meta": {"country": "RU", "region": reg}})
    for m in _PLATE_UA.finditer(t):
        ser, num, tail = m.groups()
        s = ser.translate(_UA2LAT).upper()
        if s not in _UA_SERIES or num == "0000":
            continue
        val = s + num + tail.translate(_UA2LAT).upper()
        out.append({"kind": "plate", "value": val, "raw": m.group(0), "start": m.start(), "end": m.end(),
                    "meta": {"country": "UA", "series": s}})
    return out


# --------------------------------------------------------------------------- #
# Public
# --------------------------------------------------------------------------- #

def extract(text):
    """All entities in `text`, ordered by position. Overlaps are resolved by kind priority (a card number is
    never also a phone) then length. Offsets are into the original `text`."""
    if not text:
        return []
    t = text.translate(_DIGITS)                        # 1:1 character map, so offsets stay valid
    found = _cards(t) + _crypto(t) + _phones(t) + _units(t) + _callsigns(t) + _plates(t)
    found.sort(key=lambda e: (PRIORITY[e["kind"]], -(e["end"] - e["start"]), e["start"]))
    kept = []
    for e in found:
        if not any(e["start"] < k["end"] and k["start"] < e["end"] for k in kept):
            kept.append(e)
    kept.sort(key=lambda e: (e["start"], e["end"]))
    for e in kept:
        e["raw"] = text[e["start"]:e["end"]]
    return kept
