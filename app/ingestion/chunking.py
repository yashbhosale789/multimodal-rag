import re

from langchain_core.documents import Document

from app.ingestion.parsers import Section

MAX_CHARS = 1000
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def chunk(sections: list[Section], max_chars: int = MAX_CHARS) -> list[Document]:
    docs, trail = (
        [],
        [],
    )  # trail = heading path; carried across pages so page 2 keeps page 1's headings
    for section in sections:
        blocks = []
        for block in _blocks(section.text):
            heading = HEADING.match(block)
            if heading:
                docs += _pack(blocks, trail, section.page, max_chars)
                blocks = []
                level = len(heading.group(1))
                trail = trail[: level - 1] + [
                    heading.group(2).replace("**", "").strip()
                ]
            else:
                blocks.append(block)
        docs += _pack(blocks, trail, section.page, max_chars)
    return docs


def _blocks(text: str) -> list[str]:
    text = re.sub(
        r"^(#{1,6} .*)$", r"\n\1\n", text, flags=re.M
    )  # headings always stand alone
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def _pack(
    blocks: list[str], trail: list[str], page: int | None, max_chars: int
) -> list[Document]:
    header = " > ".join(trail)
    budget = max_chars - len(header) - 2

    merged = (
        []
    )  # a table or image travels with the block before it (its title / "Figure 1 shows...")
    for b in blocks:
        if (
            merged
            and b.startswith(("|", "!["))
            and len(merged[-1]) + 2 + len(b) <= budget
        ):
            merged[-1] += "\n\n" + b
        else:
            merged.append(b)

    pieces = [p for b in merged for p in _split(b, budget)]
    metadata = {"section": header} | (
        {"page": page} if page is not None else {}
    )  # Pinecone rejects null
    return [
        Document(f"{header}\n\n{c}" if header else c, metadata=dict(metadata))
        for c in _greedy(pieces, budget, "\n\n")
    ]


def _split(block: str, budget: int) -> list[str]:
    if len(block) <= budget or block.startswith("!["):  # image descriptions stay whole
        return [block]
    if block.startswith("|"):
        lines = block.splitlines()
        return _greedy(
            lines[2:], budget, "\n", head="\n".join(lines[:2])
        )  # repeat header + |---| row
    # shortcut: a single sentence longer than the budget becomes one oversized chunk.
    return _greedy(re.split(r"(?<=[.!?])\s+", block), budget, " ")


def _greedy(parts: list[str], budget: int, sep: str, head: str = "") -> list[str]:
    out, current = [], head
    for p in parts:
        if current != head and len(current) + len(sep) + len(p) > budget:
            out.append(current)
            current = head
        current = f"{current}{sep}{p}" if current else p
    if current != head:
        out.append(current)
    return out
