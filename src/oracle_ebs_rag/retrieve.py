"""
Semantic retrieval over rag_chunks.

Pulls the top-k chunks for a query, returning rich Hit objects
ready to be assembled into an LLM prompt. Used by rag.py and the
ad-hoc search script.
"""
from __future__ import annotations

import array
from dataclasses import dataclass

from .db import connect
from .embedder import Embedder


@dataclass
class Hit:
    doc_id: int
    chunk_id: int
    note_id: str           # e.g. 'NOTE-001' (filename slug)
    title: str
    section: str
    category: str
    distance: float
    text: str


def _to_vector(vec: list[float]) -> array.array:
    return array.array("f", vec)


def retrieve(query: str, k: int = 8, embedder: Embedder | None = None) -> list[Hit]:
    """Return the top-k chunks for `query`, ranked by cosine distance ascending."""
    embedder = embedder or Embedder()
    qvec = embedder.embed([query], input_type="search_query")[0]

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.doc_id,
                   c.chunk_id,
                   d.source_path,
                   d.title,
                   c.section,
                   d.category,
                   VECTOR_DISTANCE(c.embedding, :qv, COSINE) AS dist,
                   c.chunk_text
              FROM rag_chunks c
              JOIN rag_documents d ON d.doc_id = c.doc_id
             ORDER BY dist
             FETCH FIRST :k ROWS ONLY
            """,
            qv=_to_vector(qvec), k=k,
        )
        hits = []
        for doc_id, chunk_id, src, title, section, category, dist, clob in cur.fetchall():
            text = clob.read() if hasattr(clob, "read") else str(clob)
            # Derive a stable note_id from filename for citations (NOTE-001 etc.)
            note_id = _note_id_from_path(src)
            hits.append(Hit(
                doc_id=doc_id, chunk_id=chunk_id, note_id=note_id,
                title=title, section=section, category=category,
                distance=float(dist), text=text,
            ))
    finally:
        conn.close()
    return hits


def _note_id_from_path(path: str) -> str:
    """Extract 'NOTE-001' from '.../NOTE-001-something.md'. Falls back to filename."""
    import re
    m = re.search(r"(NOTE-\d{3})", path)
    return m.group(1) if m else path.rsplit("/", 1)[-1]
