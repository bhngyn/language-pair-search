import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from language_pair_search import entities as E

def luhn_complete(prefix):            # append the check digit
    for d in "0123456789":
        if E.luhn(prefix + d):
            return prefix + d

def kinds(text):
    return [(e["kind"], e["value"]) for e in E.extract(text)]

def has(text, kind, value=None):
    return any(e["kind"] == kind and (value is None or e["value"] == value) for e in E.extract(text))

VISA = luhn_complete("453201511283036")       # 16
MC = luhn_complete("542523343010990")
AMEX = luhn_complete("37828224631000")        # 15
MIR = luhn_complete("220220022394845")
UZ = luhn_complete("860012345678901")
BAD_VISA = VISA[:-1] + str((int(VISA[-1]) + 1) % 10)
g4 = lambda n: " ".join(n[i:i + 4] for i in range(0, len(n), 4))

pos = [
    # phones
    ("тел +249 912 345 678", "phone", "+249912345678"),
    ("call +249-912-345-678 now", "phone", "+249912345678"),
    ("+380 (50) 123-45-67", "phone", "+380501234567"),
    ("+7 999 123-45-67", "phone", "+79991234567"),
    ("+7(999)1234567", "phone", "+79991234567"),
    ("00249912345678", "phone", "+249912345678"),
    ("رقم: ‏+٢٤٩٩١٢٣٤٥٦٧٨", "phone", "+249912345678"),
    ("+971 50 123 4567", "phone", "+971501234567"),
    ("whatsapp +966 512345678", "phone", "+966512345678"),
    ("+20 100 123 4567", "phone", "+201001234567"),
    ("https://wa.me/249912345678", "phone", "+249912345678"),
    ("тел: 8 (912) 345-67-89", "phone", "+79123456789"),
    ("телефон 89123456789", "phone", "+79123456789"),
    ("звони 🔹8-903-574-25-10 🔹8-905-574-43-33 🔹8-925-017-09-08", "phone", "+79250170908"),
    # crypto
    ("send to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa please", "btc", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"),
    ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "btc", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"),
    ("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4", "btc", "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"),
    ("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4", "btc", "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"),
    ("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0", "btc", None),
    ("0xdAC17F958D2ee523a2206206994597C13D831ec7", "eth", "0xdac17f958d2ee523a2206206994597c13d831ec7"),
    ("USDT TRC20: TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "trx", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"),
    # cards
    (f"карта {VISA}", "card", f"{VISA[:6]}…{VISA[-4:]}"),
    (f"карта {g4(VISA)}", "card", f"{VISA[:6]}…{VISA[-4:]}"),
    (f"карта {'-'.join(VISA[i:i+4] for i in range(0, 16, 4))}", "card", f"{VISA[:6]}…{VISA[-4:]}"),
    (f"{g4(MC)} 1500 руб", "card", f"{MC[:6]}…{MC[-4:]}"),
    (f"Amex {AMEX[:4]} {AMEX[4:10]} {AMEX[10:]}", "card", f"{AMEX[:6]}…{AMEX[-4:]}"),
    (f"Мир {MIR}", "card", f"{MIR[:6]}…{MIR[-4:]}"),
    (f"Uzcard {UZ}", "card", f"{UZ[:6]}…{UZ[-4:]}"),
    # units
    ("в/ч 12345 находится", "unit", "12345"),
    ("войсковая часть 54321", "unit", "54321"),
    ("в.ч. 32041", "unit", "32041"),
    ("В/Ч №11111", "unit", "11111"),
    ("військова частина А0123", "unit", "А0123"),
    # callsigns
    ("позывной «Волк»", "callsign", "волк"),
    ("позывной Тень был ранен", "callsign", "тень"),
    ("(позывной Ветер)", "callsign", "ветер"),
    ("п-ной Рысь", "callsign", "рысь"),
    ('позывной "Old Man"', "callsign", "old man"),
    # plates
    ("на машине А123ВС77 уехали", "plate", "А123ВС77"),
    ("A123BC77", "plate", "А123ВС77"),
    ("К777КК799", "plate", "К777КК799"),
    ("номер Х001ХХ 50", "plate", "Х001ХХ50"),
    ("АА1234ВВ", "plate", "AA1234BB"),
    ("КА 5678 ТХ", "plate", "KA5678TX"),
]
neg = [
    "https://t.me/channel/1234567890123",                 # post id / long number
    "Published 2026-09-28 at 12:30",
    "12.12.2023 15:40",
    "price 1,234,567.89 USD",
    "+7 days later",
    "+1 2 3 4 5",
    "+1000000",
    "call 1234567890123456 today",                      # 16 digits, Luhn-invalid usually
    f"card {BAD_VISA}",                                  # Luhn-invalid
    "1700000000000",                                     # ms timestamp (13 digits, starts with 1)
    "4111 1111 1111 1111",                               # placeholder, too few distinct digits
    "order 88005553535",                                 # 8-800 number without a phone word
    "id 89123456789 in list",                            # RU 8-format with no phone word
    "0x0000000000000000000000000000000000000000",
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb",                # BTC with a bad checksum
    "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5",        # bech32 bad checksum
    "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u",                # TRX bad checksum
    "0xdAC17F958D2ee523a2206206994597C13D831ec",         # 39 hex
    "В/Ч 123",                                           # too few digits
    "в/ч 123456",                                        # too many digits
    "позывной был плохой",                               # no name, lowercase filler
    "позывной не назвал",
    "А123ВС00",                                          # region 00
    "А000ВС77",                                          # 000 number
    "Б123ВС77",                                          # Б is not a plate letter
    "AB1234CD",                                          # not a UA region series
    "SKU AB-1234-CD",
    "version 2.4.1234.5678",
    "https://example.com/A123BC777x",
    "بتاريخ 2026/9/28 الساعة 10:30",
    "12345 67890 12345",
    "ref 8-903-574-25-10 8-905-574-43-33",               # a list of 8-numbers with no phone word anywhere
]

fails = 0
for text, kind, value in pos:
    ok = has(text, kind, value)
    if not ok:
        fails += 1
        print("MISS  ", repr(text), kind, value, "->", kinds(text))
for text in neg:
    got = kinds(text)
    if got:
        fails += 1
        print("FALSE+", repr(text), "->", got)

# structure checks
e = E.extract(f"пополни {g4(VISA)} и +249 912 345 678")
assert [x["kind"] for x in e] == ["card", "phone"], e
card = e[0]
assert card["value"] == f"{VISA[:6]}…{VISA[-4:]}" and card["raw"] == g4(VISA), card
assert VISA not in repr(card["value"]) and VISA not in repr(card["meta"])
t = "xx ٠١٢ +٢٤٩ ٩١٢ ٣٤٥ ٦٧٨"
p = E.extract(t)[0]
assert t[p["start"]:p["end"]] == p["raw"]                 # offsets stay valid through digit folding
# overlap: a card number is never also a phone / plate
assert kinds(f"+{VISA}") == [] or all(k != "card" for k, _ in kinds(f"+{VISA}"))
print(f"{len(pos)} positives, {len(neg)} negatives, {fails} failures")
sys.exit(1 if fails else 0)
