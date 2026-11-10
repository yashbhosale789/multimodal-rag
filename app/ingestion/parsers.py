from dataclasses import dataclass
from pathlib import Path

import pymupdf4llm
from docx import Document
from docx.table import Table


@dataclass
class Section:
    text: str  # Markdown; images appear as ![](path) at their original position
    page: int | None  # None for DOCX: it has no pages until a renderer lays it out


def parse(path: Path, image_dir: Path) -> list[Section]:
    image_dir.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path, image_dir)
    if suffix == ".docx":
        return _parse_docx(path, image_dir)
    raise ValueError(f"Unsupported file type: {suffix}")


def _parse_pdf(path: Path, image_dir: Path) -> list[Section]:
    # shortcut: tables continuing onto the next page lose their header and flatten; merge across pages if the answer key shows misses.
    pages = pymupdf4llm.to_markdown(str(path), page_chunks=True, write_images=True, image_path=str(image_dir))
    return [Section(p["text"], p["metadata"]["page_number"]) for p in pages]


def _parse_docx(path: Path, image_dir: Path) -> list[Section]:
    doc = Document(str(path))
    blocks, n_images = [], 0
    for block in doc.iter_inner_content():  # paragraphs and tables, in document order
        if isinstance(block, Table):
            blocks.append(_table_to_markdown(block))
            continue
        style = block.style.name
        if style == "Title":
            prefix = "# "
        elif style.startswith("Heading ") and style.split()[-1].isdigit():
            prefix = "#" * (int(style.split()[-1]) + 1) + " "
        else:
            prefix = ""
        if block.text.strip():
            blocks.append(prefix + block.text.strip())
        for rel_id in block._p.xpath(".//a:blip/@r:embed"):  # images anchored in this paragraph
            part = doc.part.related_parts[rel_id]
            n_images += 1
            img = image_dir / f"{path.name}-{n_images:02d}{Path(part.partname).suffix}"
            img.write_bytes(part.blob)
            blocks.append(f"![]({img.as_posix()})")
    return [Section("\n\n".join(blocks), None)]


def _table_to_markdown(table: Table) -> str:
    rows = [[c.text.strip().replace("\n", " ").replace("|", "\\|") for c in r.cells] for r in table.rows]
    header, *body = rows
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)
