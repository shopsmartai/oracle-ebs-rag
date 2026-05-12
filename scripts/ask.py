#!/usr/bin/env python
"""
ask.py — ask a question, get a grounded answer with citations.

Streams the answer to stdout, then prints retrieval distances and
token usage so you can see the cost + cache hit rate.

Usage:
    uv run python scripts/ask.py "concurrent request stuck in pending normal"
    uv run python scripts/ask.py "smtp tls cert rotated — how do I fix mailer"
"""
import sys

from oracle_ebs_rag.rag import ask, RagResult


def main():
    if len(sys.argv) < 2:
        print('Usage: uv run python scripts/ask.py "<your question>"')
        sys.exit(1)
    question = " ".join(sys.argv[1:])

    print(f"\nQ: {question}\n")
    print("─" * 72)
    print("A: ", end="", flush=True)

    final_result: RagResult | None = None
    for piece in ask(question, k=6, stream=True):
        if isinstance(piece, RagResult):
            final_result = piece
        else:
            print(piece, end="", flush=True)

    if final_result is None:
        return

    print("\n" + "─" * 72)
    print("Retrieved chunks:")
    for h in final_result.hits:
        print(f"  [{h.distance:.3f}] {h.note_id} §{h.section:<12} ({h.title!r:.60})")

    u = final_result.usage
    in_tok = u["input_tokens"]
    out_tok = u["output_tokens"]
    cache_r = u["cache_read_input_tokens"]
    cache_w = u["cache_creation_input_tokens"]

    # Claude Sonnet 4.6 pricing (approx, USD per million tokens):
    cost = (
        in_tok   * 3.00 / 1e6 +
        cache_r  * 0.30 / 1e6 +
        cache_w  * 3.75 / 1e6 +
        out_tok  * 15.0 / 1e6
    )
    print(f"\nUsage: input={in_tok}  cache_read={cache_r}  "
          f"cache_write={cache_w}  output={out_tok}")
    print(f"Cost:  ${cost:.5f}")


if __name__ == "__main__":
    main()
