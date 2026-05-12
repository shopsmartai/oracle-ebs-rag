"""
Ingestion CLI.

Reads markdown notes from data/synthetic_notes/ (or path given as
arg), parses frontmatter + sections, embeds each section via Cohere,
and inserts into rag_documents + rag_chunks.

Idempotent: re-ingesting the same file deletes the old document
(cascade-deletes its chunks) and re-inserts.

Usage:
    uv run ingest
    uv run ingest path/to/notes
"""
from __future__ import annotations

import array
import sys
from pathlib import Path

from .chunker import ParsedNote, parse_all
from .db import connect
from .embedder import Embedder


DEFAULT_DIR = Path("data/synthetic_notes")


def to_vector(vec: list[float]) -> array.array:
    """Convert Python list[float] -> float32 array for oracledb VECTOR binding."""
    return array.array("f", vec)


def upsert_note(cur, note: ParsedNote, vectors: list[list[float]]) -> int:
    """Delete + re-insert the document and all its chunks. Returns chunk count."""
    # 1. Remove existing document (cascade deletes chunks via FK ON DELETE CASCADE)
    cur.execute(
        "DELETE FROM rag_documents WHERE source_path = :p",
        p=note.source_path,
    )

    # 2. Insert new document
    doc_id_var = cur.var(int)
    tags_str = ",".join(note.tags) if note.tags else None
    cur.execute(
        """
        INSERT INTO rag_documents
            (source_path, source_type, title, category, tags)
        VALUES (:p, :t, :ti, :c, :tg)
        RETURNING doc_id INTO :id
        """,
        p=note.source_path, t="md", ti=note.title,
        c=note.category, tg=tags_str, id=doc_id_var,
    )
    doc_id = doc_id_var.getvalue()[0]

    # 3. Insert chunks (batched)
    rows = []
    for idx, (chunk, vec) in enumerate(zip(note.chunks, vectors)):
        rows.append((
            doc_id, idx, chunk.section, chunk.text,
            chunk.token_count, to_vector(vec),
        ))
    cur.executemany(
        """
        INSERT INTO rag_chunks
            (doc_id, chunk_index, section, chunk_text,
             token_count, embedding)
        VALUES (:1, :2, :3, :4, :5, :6)
        """,
        rows,
    )
    return len(rows)


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    if not directory.exists():
        print(f"ERROR: {directory} does not exist", file=sys.stderr)
        return 1

    print(f"Parsing notes in {directory}/ ...")
    notes = parse_all(directory)
    if not notes:
        print("No .md files found.", file=sys.stderr)
        return 1
    print(f"  parsed {len(notes)} notes")

    embedder = Embedder()
    total_chunks = 0

    conn = connect()
    try:
        cur = conn.cursor()
        for note in notes:
            n_chunks = len(note.chunks)
            print(f"  [{note.note_id}] {note.title!r} -> {n_chunks} chunks")
            if n_chunks == 0:
                print("    (no chunks; skipping)")
                continue
            texts = [c.text for c in note.chunks]
            vectors = embedder.embed(texts, input_type="search_document")
            inserted = upsert_note(cur, note, vectors)
            total_chunks += inserted
        conn.commit()
    finally:
        conn.close()

    print(f"\nDone. {len(notes)} documents, {total_chunks} chunks total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
