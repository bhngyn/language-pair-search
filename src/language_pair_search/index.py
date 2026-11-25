"""
FTS5 helpers: the table layout the query builder in textnorm.py expects, and text -> row values.

textnorm.fts_query() / lexicon.expand() produce expressions for a table created with fts_ddl(): the columns
`norm` and `stems` hold index_row() output, and the optional `meta` column holds names (channel, author...)
that a text search must not match (see textnorm.fts_scoped). fts_ddl(..., contentless=True) builds the same index
without storing the text (smaller; no snippet()/highlight()). The tokenizer must be `unicode61 remove_diacritics 2`.
Python's sqlite3 must be built with FTS5.
"""

from . import textnorm, translit

FTS_VERSION = "3"     # bump (with translit.KEY_VERSION) when the norm/stems format changes: reindex stored text


CONTENTLESS_MIN_SQLITE = (3, 43, 0)      # contentless_delete=1 (needed to replace rows) arrived in SQLite 3.43


def fts_ddl(table, meta=False, contentless=False):
    """CREATE VIRTUAL TABLE statement for a search index over one kind of text.

    contentless=True stores only the index, not a copy of the norm/stems/meta text (FTS5 `content=''`), which
    roughly halves the table on disk. MATCH, bm25() and rowids work as before; reading the columns back,
    snippet() and highlight() do not (they return NULL), so keep the original text in your own table and
    highlight from it. `contentless_delete=1` keeps index_text()'s replace-a-row working; it needs SQLite >= 3.43.
    """
    cols = "norm, stems, meta" if meta else "norm, stems"
    opts = "tokenize = 'unicode61 remove_diacritics 2'"
    if contentless:
        import sqlite3
        if sqlite3.sqlite_version_info < CONTENTLESS_MIN_SQLITE:
            raise RuntimeError(f"contentless FTS tables need SQLite >= 3.43 (this is {sqlite3.sqlite_version})")
        opts = "content = '', contentless_delete = 1, " + opts
    return f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5({cols}, {opts})"


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
