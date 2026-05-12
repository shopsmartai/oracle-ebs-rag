"""
RAG orchestrator: retrieve relevant chunks, build a grounded prompt,
call Claude, return answer + citations.

Design choices:
  * Context is sent in the *system* prompt with cache_control = ephemeral.
    This caches the (often-reused) context across follow-up turns and
    cuts cost ~80-90% on repeated questions. Cache TTL is 5 minutes.
  * The system prompt is strict about citations and "say if you don't know".
    DBAs hate confident hallucinations.
  * Answers are streamed so the UI feels responsive (CLI prints chunks
    as they arrive).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import anthropic

from .config import settings
from .retrieve import Hit, retrieve


SYSTEM_INSTRUCTIONS = """You are an Oracle E-Business Suite R12.2.11
expert assistant. You answer using ONLY the provided context chunks.

Rules:
- Cite sources inline as [NOTE-XXX §section], e.g. [NOTE-001 §resolution]
- If the context does not contain enough information, say so explicitly
  and suggest what additional information would be needed.
- Be terse. DBAs hate fluff. Use bullet points and code blocks where
  appropriate.
- Prefer concrete SQL, navigation paths, and profile-option names over
  generic advice.
- Never invent commands, table names, or doc IDs not present in the
  context. If you're unsure, say so.
"""


@dataclass
class RagResult:
    answer: str
    hits: list[Hit]
    usage: dict


def _format_context(hits: list[Hit]) -> str:
    """Format retrieved chunks into a labeled, citable context block."""
    blocks = []
    for h in hits:
        header = f"[{h.note_id} §{h.section}]  (distance {h.distance:.3f})"
        blocks.append(f"{header}\n{h.text}")
    return "\n\n---\n\n".join(blocks)


def ask(question: str, k: int = 6, stream: bool = False) -> RagResult | Iterator[str]:
    """Answer `question` using retrieved context.

    If stream=True, returns a generator yielding text deltas as they
    arrive from Claude. Otherwise returns RagResult with full answer.
    """
    s = settings()
    if not s.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing in .env")

    hits = retrieve(question, k=k)
    context = _format_context(hits)

    client = anthropic.Anthropic(api_key=s.anthropic_api_key)

    system_blocks = [
        {"type": "text", "text": SYSTEM_INSTRUCTIONS},
        # Cache the (potentially long) context across the 5-min TTL.
        # On follow-up questions where context is the same, this saves cost.
        {
            "type": "text",
            "text": f"--- RETRIEVED CONTEXT ---\n{context}\n--- END CONTEXT ---",
            "cache_control": {"type": "ephemeral"},
        },
    ]

    if stream:
        return _stream(client, s.anthropic_model, system_blocks, question, hits)

    resp = client.messages.create(
        model=s.anthropic_model,
        max_tokens=1024,
        system=system_blocks,
        messages=[{"role": "user", "content": question}],
    )
    answer = resp.content[0].text
    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_creation_input_tokens": getattr(
            resp.usage, "cache_creation_input_tokens", 0
        ) or 0,
        "cache_read_input_tokens": getattr(
            resp.usage, "cache_read_input_tokens", 0
        ) or 0,
    }
    return RagResult(answer=answer, hits=hits, usage=usage)


def _stream(client, model, system_blocks, question, hits):
    """Yield text deltas; final yield is a RagResult sentinel."""
    with client.messages.stream(
        model=model,
        max_tokens=1024,
        system=system_blocks,
        messages=[{"role": "user", "content": question}],
    ) as st:
        for delta in st.text_stream:
            yield delta
        final = st.get_final_message()
    # Tail sentinel — print(end=...) friendly
    yield "\n"
    yield RagResult(
        answer="<streamed>",
        hits=hits,
        usage={
            "input_tokens": final.usage.input_tokens,
            "output_tokens": final.usage.output_tokens,
            "cache_creation_input_tokens": getattr(
                final.usage, "cache_creation_input_tokens", 0
            ) or 0,
            "cache_read_input_tokens": getattr(
                final.usage, "cache_read_input_tokens", 0
            ) or 0,
        },
    )
