"""
FTS5 helpers: the table layout the query builder in textnorm.py expects, and text -> row values.

textnorm.fts_query() / lexicon.expand() produce expressions for a table created with fts_ddl(): the columns
`norm` and `stems` hold index_row() output, and the optional `meta` column holds names (channel, author...)
that a text search must not match (see textnorm.fts_scoped). The tokenizer must be `unicode61 remove_diacritics 2`.
Python's sqlite3 must be built with FTS5.
"""

from . import textnorm, translit

FTS_VERSION = "3"     # bump (with translit.KEY_VERSION) when the norm/stems format changes: reindex stored text


def fts_ddl(table, meta=False):
    """CREATE VIRTUAL TABLE statement for a search index over one kind of text."""
    cols = "norm, stems, meta" if meta else "norm, stems"
    return f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5({cols}, tokenize = 'unicode61 remove_diacritics 2')"


def index_row(text, meta_parts=()):
    """(norm, stems, meta) for one document. meta is the normalised join of meta_parts ("" when none)."""
    norm = textnorm.normalize(text)
    meta = textnorm.normalize(" ".join(str(m) for m in meta_parts if m))
    return norm, textnorm.index_stems(norm), meta


def index_text(con, table, rowid, text, meta_parts=None):
    """(Re)index one document: replaces the row `rowid` of an FTS table made with fts_ddl(). The caller commits.
    Pass meta_parts (even an empty list) only for a table created with meta=True."""
    norm, stems, meta = index_row(text, meta_parts or ())
    con.execute(f"DELETE FROM {table} WHERE rowid = ?", (rowid,))
    if meta_parts is None:
        con.execute(f"INSERT INTO {table}(rowid, norm, stems) VALUES (?,?,?)", (rowid, norm, stems))
    else:
        con.execute(f"INSERT INTO {table}(rowid, norm, stems, meta) VALUES (?,?,?,?)", (rowid, norm, stems, meta))
