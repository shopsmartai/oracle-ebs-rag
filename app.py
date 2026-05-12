"""
Talk to EBS — Streamlit chat UI.

Run with:
    uv run streamlit run app.py

Features:
- Streaming answers (feels alive)
- Multi-turn chat history kept in session_state
- Per-message expandable "Sources" panel
- Sidebar: cumulative cost, cache hit rate, model/k controls, reset
"""
from __future__ import annotations

import streamlit as st
import anthropic

from oracle_ebs_rag.config import settings
from oracle_ebs_rag.retrieve import retrieve, Hit
from oracle_ebs_rag.rag import SYSTEM_INSTRUCTIONS, _format_context

# Sonnet 4.6 pricing (USD per million tokens). Update if model changes.
PRICING = {
    "input":       3.00 / 1e6,
    "cache_read":  0.30 / 1e6,
    "cache_write": 3.75 / 1e6,
    "output":     15.0 / 1e6,
}


# ─── Page setup ──────────────────────────────────────────────────────
st.set_page_config(page_title="Talk to EBS", page_icon="📘", layout="wide")
st.title("Talk to EBS")
st.caption(
    "Oracle E-Business Suite R12.2.11 assistant • "
    "Oracle 23ai vector search + Claude • Synthetic dataset"
)

# ─── Helpers (must be defined before sidebar uses them) ──────────────
def _empty_usage() -> dict:
    return {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0}


# ─── Session state ───────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "usage" not in st.session_state:
    st.session_state.usage = _empty_usage()


# ─── Sidebar ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    k = st.slider("Chunks retrieved (k)", 3, 12, 6)
    model = st.text_input("Model", value=settings().anthropic_model)
    if st.button("Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.usage = _empty_usage()
        st.rerun()

    st.divider()
    st.subheader("Session cost")
    u = st.session_state.get("usage") or _empty_usage()
    cost = (
        u["input"]       * PRICING["input"] +
        u["cache_read"]  * PRICING["cache_read"] +
        u["cache_write"] * PRICING["cache_write"] +
        u["output"]      * PRICING["output"]
    )
    total_input_like = u["input"] + u["cache_read"] + u["cache_write"]
    hit_rate = (u["cache_read"] / total_input_like) if total_input_like else 0.0
    st.metric("USD spent", f"${cost:.5f}")
    st.metric("Cache hit rate", f"{hit_rate:.0%}")
    st.caption(
        f"input={u['input']}  "
        f"cache_read={u['cache_read']}  "
        f"cache_write={u['cache_write']}  "
        f"output={u['output']}"
    )


# ─── Render history ──────────────────────────────────────────────────
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("hits"):
            with st.expander(f"Sources ({len(m['hits'])})"):
                for h in m["hits"]:
                    st.markdown(
                        f"**[{h.distance:.3f}] {h.note_id} §{h.section}** — {h.title}"
                    )
                    st.caption(h.text[:400] + ("…" if len(h.text) > 400 else ""))


# ─── Input loop ──────────────────────────────────────────────────────
prompt = st.chat_input("Ask about EBS configuration, errors, or workflows…")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Retrieve
    with st.spinner("Searching ingested notes…"):
        hits: list[Hit] = retrieve(prompt, k=k)
        context = _format_context(hits)

    # Generate
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full = ""

        client = anthropic.Anthropic(api_key=settings().anthropic_api_key)
        system_blocks = [
            {"type": "text", "text": SYSTEM_INSTRUCTIONS},
            {
                "type": "text",
                "text": f"--- RETRIEVED CONTEXT ---\n{context}\n--- END CONTEXT ---",
                "cache_control": {"type": "ephemeral"},
            },
        ]

        # Reconstruct prior turns (without re-injecting context — it's in system)
        api_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages
        ]

        with client.messages.stream(
            model=model,
            max_tokens=1024,
            system=system_blocks,
            messages=api_messages,
        ) as st_stream:
            for delta in st_stream.text_stream:
                full += delta
                placeholder.markdown(full + "▌")
            final = st_stream.get_final_message()

        placeholder.markdown(full)

        # Update usage
        st.session_state.usage["input"]       += final.usage.input_tokens
        st.session_state.usage["output"]      += final.usage.output_tokens
        st.session_state.usage["cache_read"]  += getattr(final.usage, "cache_read_input_tokens", 0) or 0
        st.session_state.usage["cache_write"] += getattr(final.usage, "cache_creation_input_tokens", 0) or 0

        with st.expander(f"Sources ({len(hits)})"):
            for h in hits:
                st.markdown(
                    f"**[{h.distance:.3f}] {h.note_id} §{h.section}** — {h.title}"
                )
                st.caption(h.text[:400] + ("…" if len(h.text) > 400 else ""))

    st.session_state.messages.append({
        "role": "assistant", "content": full, "hits": hits,
    })
