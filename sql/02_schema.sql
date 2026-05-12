-- 02_schema.sql
-- Creates the RAG tables in the RAGAPP schema.
-- Run as RAGAPP connected to FREEPDB1.

-- Idempotent
BEGIN
  FOR t IN (SELECT table_name FROM user_tables
             WHERE table_name IN ('RAG_CHUNKS','RAG_DOCUMENTS'))
  LOOP
    EXECUTE IMMEDIATE 'DROP TABLE ' || t.table_name || ' CASCADE CONSTRAINTS PURGE';
  END LOOP;
END;
/

CREATE TABLE rag_documents (
  doc_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_path  VARCHAR2(1000) NOT NULL,
  source_type  VARCHAR2(50),
  title        VARCHAR2(500),
  category     VARCHAR2(100),
  tags         VARCHAR2(500),
  ingested_at  TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE rag_chunks (
  chunk_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  doc_id       NUMBER NOT NULL,
  chunk_index  NUMBER NOT NULL,
  section      VARCHAR2(100),         -- 'symptom','cause','resolution', etc.
  chunk_text   CLOB   NOT NULL,
  token_count  NUMBER,
  embedding    VECTOR(1024, FLOAT32), -- Cohere embed-english-v3.0 dim
  CONSTRAINT fk_chunks_doc
    FOREIGN KEY (doc_id) REFERENCES rag_documents(doc_id)
    ON DELETE CASCADE
);

CREATE INDEX rag_chunks_doc_idx ON rag_chunks(doc_id);

-- Note: VECTOR INDEX (HNSW) is intentionally deferred.
-- Oracle 23ai HNSW requires vector_memory_size > 0, which needs a DB
-- restart. For ~500 chunks, brute-force VECTOR_DISTANCE is fast enough
-- (<50ms). We will add the HNSW index later as a portfolio "optimization"
-- chapter with before/after benchmarks (great blog post material).

-- Verify
COL table_name FORMAT A20
COL column_name FORMAT A20
COL data_type FORMAT A30
SELECT table_name, column_name, data_type, data_length
  FROM user_tab_columns
 WHERE table_name IN ('RAG_DOCUMENTS','RAG_CHUNKS')
 ORDER BY table_name, column_id;

EXIT;
