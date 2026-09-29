# Tests

Plain Python asserts, no framework. From the repo root:

```bash
.venv/bin/python tests/test_search_core.py   # normalisation, obfuscation, stemming, NEAR, expansion, FTS helpers, place matching
.venv/bin/python tests/test_entities.py      # phones, wallets, cards (Luhn), unit numbers, plates
```

`fixtures/dictionary_fixture.db` is a tiny dictionary built by `fixtures/make_fixture.py`, so the tests do not need
the real 50 MB `dictionary.db`.
