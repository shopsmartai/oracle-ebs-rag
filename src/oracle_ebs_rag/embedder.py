"""
Cohere embedder.

Wraps the Cohere SDK with:
  - automatic batching (Cohere accepts up to 96 texts per call)
  - input_type discrimination (search_document vs search_query —
    these produce different embeddings; using the wrong one hurts
    retrieval recall noticeably)
  - graceful retry on transient errors (rate limit, network)
"""
from __future__ import annotations

import time
from typing import Literal

import cohere

from .config import settings


BATCH_SIZE = 96  # Cohere embed-v3 max texts per call

InputType = Literal["search_document", "search_query"]


class Embedder:
    def __init__(self):
        s = settings()
        self.client = cohere.ClientV2(api_key=s.cohere_api_key)
        self.model = s.cohere_embed_model

    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        """Embed N texts, returning N 1024-dim float vectors."""
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            vecs = self._embed_batch_with_retry(batch, input_type)
            all_vecs.extend(vecs)
        return all_vecs

    def _embed_batch_with_retry(
        self, batch: list[str], input_type: InputType, max_attempts: int = 3
    ) -> list[list[float]]:
        last_err: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.client.embed(
                    texts=batch,
                    model=self.model,
                    input_type=input_type,
                    embedding_types=["float"],
                )
                return resp.embeddings.float_
            except cohere.errors.TooManyRequestsError as e:
                last_err = e
                wait = 2**attempt
                print(f"  rate limited; sleeping {wait}s and retrying")
                time.sleep(wait)
            except Exception as e:
                last_err = e
                print(f"  embed attempt {attempt} failed: {e}")
                time.sleep(1)
        raise RuntimeError(f"Embed failed after {max_attempts} attempts: {last_err}")
