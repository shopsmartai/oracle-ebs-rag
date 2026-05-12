-- 01_users.sql
-- Creates RAGAPP (owner of RAG tables) and MCP_RO (read-only for MCP).
-- Run as SYSTEM connected to FREEPDB1.

BEGIN
  FOR u IN (SELECT username FROM dba_users
             WHERE username IN ('RAGAPP','MCP_RO'))
  LOOP
    EXECUTE IMMEDIATE 'DROP USER ' || u.username || ' CASCADE';
  END LOOP;
END;
/

-- Application user (owns RAG tables)
CREATE USER ragapp IDENTIFIED BY "ragapp_dev_pwd"
  DEFAULT TABLESPACE USERS
  QUOTA UNLIMITED ON USERS;
-- CREATE INDEX is implicit when you own the table; not a grantable priv.
GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, CREATE VIEW TO ragapp;

-- Read-only user for the MCP server
CREATE USER mcp_ro IDENTIFIED BY "mcp_ro_dev_pwd";
GRANT CREATE SESSION TO mcp_ro;
-- SELECT_CATALOG_ROLE gives SELECT on all V$ and DBA_* views.
-- This single grant replaces the explicit v_$sql / v_$session / v_$pdbs
-- grants from the first version of this file.
GRANT SELECT_CATALOG_ROLE TO mcp_ro;

-- Verify users
COL username           FORMAT A12
COL account_status     FORMAT A18
COL default_tablespace FORMAT A20
SELECT username, account_status, default_tablespace
  FROM dba_users
 WHERE username IN ('RAGAPP','MCP_RO');

EXIT;
