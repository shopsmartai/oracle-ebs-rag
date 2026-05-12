"""
Markdown-section chunker for synthetic resolution notes.

Why section-based, not sliding-window?
Each resolution note is structured (Symptom / Diagnosis / Root cause /
Resolution / Verified on / References). Splitting on H2 headings keeps
each chunk semantically coherent: a "Symptom" chunk only contains
symptom text, so a similarity search for "queue is stuck" lands on
the Symptom chunks first — exactly where the user's question maps.

Sliding-window over the whole note would mix Symptom + Resolution
text in the same chunk, polluting embeddings and reducing retrieval
quality.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter


@dataclass
class Chunk:
    section: str       # 'symptom', 'diagnosis', 'root-cause', 'resolution', etc.
    text: str          # the chunk content WITH title + section prefix for embedding context
    token_count: int   # rough estimate (chars/4)


@dataclass
class ParsedNote:
    source_path: str
    note_id: str        # e.g. 'NOTE-001'
    title: str          # the H1 heading
    category: str
    severity: str
    tags: list[str]
    metadata: dict      # all frontmatter
    chunks: list[Chunk]


# Map H2 heading text -> short section slug used in DB.
SECTION_SLUGS = {
    "symptom":          "symptom",
    "diagnosis steps":  "diagnosis",
    "diagnosis":        "diagnosis",
    "root cause":       "root-cause",
    "resolution":       "resolution",
    "verified on":      "verified-on",
    "references":       "references",
    "notes":            "notes",
}


def parse_note(path: Path) -> ParsedNote:
    """Parse one .md file into frontmatter + section-based chunks."""
    post = frontmatter.load(path)
    body = post.content

    # Extract H1 as title; fall back to filename.
    h1_match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    title = h1_match.group(1).strip() if h1_match else path.stem

    # Split body on H2 headings ("^## ...").
    # re.split with a capturing group keeps the heading text in the result list.
    parts = re.split(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    # parts = [preamble, heading_1, content_1, heading_2, content_2, ...]

    chunks: list[Chunk] = []
    for heading, content in zip(parts[1::2], parts[2::2]):
        section_slug = SECTION_SLUGS.get(heading.strip().lower(), "other")
        content = content.strip()
        if not content:
            continue
        # Each chunk's embed text includes the title + section so the
        # embedder has context. This noticeably improves retrieval.
        embed_text = f"# {title}\n## {heading.strip()}\n{content}"
        chunks.append(Chunk(
            section=section_slug,
            text=embed_text,
            token_count=len(embed_text) // 4,  # rough; good enough for budgets
        ))

    return ParsedNote(
        source_path=str(path),
        note_id=post.metadata.get("id", path.stem),
        title=title,
        category=post.metadata.get("category", "uncategorized"),
        severity=post.metadata.get("severity", "unknown"),
        tags=post.metadata.get("tags", []) or [],
        metadata=dict(post.metadata),
        chunks=chunks,
    )


def parse_all(directory: Path) -> list[ParsedNote]:
    """Parse every .md in `directory` (non-recursive)."""
    return [parse_note(p) for p in sorted(directory.glob("*.md"))]
