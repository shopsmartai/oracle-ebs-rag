#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["oracledb>=2.5.0"]
# ///
"""
hello_vector.py — first proof that vector search works in Oracle 23ai.

the gvenzl image because of macOS<->Linux Out-of-Band break issues).
Without this, the client sends an OOB-aware connect packet and the
server resets the connection mid-handshake.
"""
import array
import oracledb

DSN      = "oracle23ai.orb.local:1521/FREEPDB1"
USER     = "ragapp"
PASSWORD = "ragapp_dev_pwd"


def one_hot(dim: int, position: int) -> array.array:
    vec = [0.0] * dim
    vec[position] = 1.0
    return array.array("f", vec)


def main():
    conn = oracledb.connect(
        user=USER, password=PASSWORD, dsn=DSN
    )
    cur = conn.cursor()

    cur.execute("DELETE FROM rag_chunks")
    cur.execute("DELETE FROM rag_documents")

    doc_id_var = cur.var(int)
    cur.execute("""
        INSERT INTO rag_documents (source_path, source_type, title, category)
        VALUES ('hello.md', 'md', 'Hello Vector', 'demo')
        RETURNING doc_id INTO :id
    """, id=doc_id_var)
    doc_id = doc_id_var.getvalue()[0]

    seed_chunks = [
        ("Concurrent manager queue stuck", 0),
        ("Workflow mailer not sending",    100),
        ("GL period close failing",        500),
    ]
    for idx, (text, hot) in enumerate(seed_chunks):
        cur.execute("""
            INSERT INTO rag_chunks
                (doc_id, chunk_index, section, chunk_text,
                 token_count, embedding)
            VALUES (:d, :i, 'symptom', :t, :tc, :e)
        """, d=doc_id, i=idx, t=text, tc=len(text) // 4,
             e=one_hot(1024, hot))

    conn.commit()

    qvec = one_hot(1024, 100)
    cur.execute("""
        SELECT chunk_index,
               VECTOR_DISTANCE(embedding, :qv, COSINE) AS dist
          FROM rag_chunks
         ORDER BY dist
    """, qv=qvec)

    print(f"\n{'CHUNK_INDEX':<13} {'COSINE_DISTANCE':<18}")
    print("-" * 31)
    for chunk_idx, dist in cur.fetchall():
        print(f"{chunk_idx:<13} {dist:.6f}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
