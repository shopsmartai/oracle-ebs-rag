"""
Oracle connection helper.

Wraps oracledb with project-specific defaults:
  - reads DSN/user/password from Settings (which loads .env)
  - context-manager API so callers don't leak cursors
  - autocommit OFF (explicit conn.commit() — RAG ingestion is batched)

If you ever need to disable OOB for the gvenzl image on macOS, add
  oracledb.connect(..., disable_oob=True)
We discovered during smoke testing that connecting via OrbStack's
*.orb.local hostname avoids the port-forwarding NAT path entirely
and makes disable_oob unnecessary. Document that in the README.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import oracledb

from .config import settings


def connect() -> oracledb.Connection:
    """Open a new Oracle connection using settings from .env."""
    s = settings()
    return oracledb.connect(user=s.ora_user, password=s.ora_password, dsn=s.ora_dsn)


@contextmanager
def cursor() -> Iterator[oracledb.Cursor]:
    """One-shot cursor context: opens connection, yields cursor, commits on success."""
    conn = connect()
    try:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        finally:
            cur.close()
    finally:
        conn.close()
