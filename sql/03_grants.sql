-- 03_grants.sql
-- Explicit SELECT grants from RAGAPP to MCP_RO.
-- Run as RAGAPP.

GRANT SELECT ON rag_documents TO mcp_ro;
GRANT SELECT ON rag_chunks    TO mcp_ro;

-- Synonyms so mcp_ro can query without schema prefix
-- (run as SYSTEM since we need CREATE PUBLIC SYNONYM)
EXIT;
