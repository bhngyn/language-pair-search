"""Cross-script (Arabic / Russian / Ukrainian <-> English) search: normalisation, transliteration keys,
dictionary expansion, place lookup, pattern entities."""

from . import entities, index, lexicon, textnorm, translit
from .index import fts_ddl, index_row, index_text
from .lexicon import Edits, expand, find_places, place, set_dictionary
from .textnorm import fts_query, normalize

__version__ = "0.1.0"
