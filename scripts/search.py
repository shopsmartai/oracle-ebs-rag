#!/usr/bin/env python
"""
search.py — quick CLI to test semantic retrieval over ingested notes.

Embeds the query (input_type='search_query', which differs from
'search_document' used at ingest time) and finds the closest chunks
via Oracle's VECTOR_DISTANCE.

Usage:
    uv run python scripts/search.py "concurrent request stuck pending"
"""
import sys

from oracle_ebs_rag.db import connect
from oracle_ebs_rag.embedder import Embedder
from oracle_ebs_rag.ingest import to_vector


def search(query: str, k: int = 5):
    qvec = Embedder().embed([query], input_type="search_query")[0]

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.title,
                   c.section,
                   VECTOR_DISTANCE(c.embedding, :qv, COSINE) AS dist,
                   SUBSTR(DBMS_LOB.SUBSTR(c.chunk_text, 240, 1), 1, 240) AS preview
              FROM rag_chunks c
              JOIN rag_documents d ON d.doc_id = c.doc_id
             ORDER BY dist
             FETCH FIRST :k ROWS ONLY
            """,
            qv=to_vector(qvec), k=k,
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    print(f"\nQuery: {query!r}\n" + "=" * 72)
    for title, section, dist, preview in rows:
        print(f"\n[{dist:.4f}] {title} — {section}")
        print(f"  {preview!r}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/search.py <query>")
        sys.exit(1)
    search(" ".join(sys.argv[1:]))
