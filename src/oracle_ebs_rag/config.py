"""
Typed configuration loaded from .env.

Centralizes all environment variable access so the rest of the code
doesn't sprinkle os.environ calls everywhere. Fails fast at import
time with a clear message if a required key is missing.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env once at module import. Walks up from cwd looking for .env.
load_dotenv()


class Settings(BaseModel):
    # Oracle (app user — owns rag_documents and rag_chunks)
    ora_user: str = Field(default_factory=lambda: _required("ORA_USER"))
    ora_password: str = Field(default_factory=lambda: _required("ORA_PASSWORD"))
    ora_dsn: str = Field(default_factory=lambda: _required("ORA_DSN"))

    # Oracle (read-only user — used by MCP server later, not by ingest)
    ora_ro_user: str = Field(default_factory=lambda: os.environ.get("ORA_RO_USER", ""))
    ora_ro_password: str = Field(default_factory=lambda: os.environ.get("ORA_RO_PASSWORD", ""))

    # Cohere
    cohere_api_key: str = Field(default_factory=lambda: _required("COHERE_API_KEY"))
    cohere_embed_model: str = Field(
        default_factory=lambda: os.environ.get("COHERE_EMBED_MODEL", "embed-english-v3.0")
    )

    # Anthropic (only required for retrieval/answer steps later)
    anthropic_api_key: str = Field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = Field(
        default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    )


def _required(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {key}\n"
            f"Set it in .env (see .env.example for the template)."
        )
    return val


@lru_cache(maxsize=1)
def settings() -> Settings:
    """Cached settings — call this everywhere instead of re-instantiating."""
    return Settings()
