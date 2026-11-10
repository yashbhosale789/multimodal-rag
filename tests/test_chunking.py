from pathlib import Path

from app.ingestion.chunking import chunk
from app.ingestion.parsers import Section, parse

SAMPLES = Path(__file__).parent.parent / "samples"


def test_pdf_chunks_keep_structure_and_breadcrumbs(tmp_path):
    docs = chunk(parse(SAMPLES / "Acme_Annual_Report_2025.pdf", tmp_path))
    assert all(len(d.page_content) <= 1000 for d in docs)

    table = next(d for d in docs if "Net income" in d.page_content)
    assert table.page_content.startswith("Acme Corp Annual Report 2025 > 1. Company Overview")
    assert "Table 1: Financial Summary" in table.page_content and "|**Metric**|" in table.page_content

    figure = next(d for d in docs if "Figure 1 shows" in d.page_content)
    assert "![" in figure.page_content  # image stays with its lead-in sentence

    continued = next(d for d in docs if "Corvo Polymers" in d.page_content)
    assert continued.metadata == {"section": "Acme Corp Annual Report 2025 > 2. Supply Chain", "page": 2}


def test_docx_chunks_have_no_page_key(tmp_path):
    docs = chunk(parse(SAMPLES / "Zentrix_Supplier_Profile.docx", tmp_path))
    assert docs and all("page" not in d.metadata for d in docs)
    assert any(d.metadata["section"] == "Zentrix Minerals - Supplier Profile > Mine Sites" for d in docs)


def test_oversized_table_is_split_by_rows_with_header_repeated():
    rows = "\n".join(f"| item {i} | {i * 100} |" for i in range(30))
    docs = chunk([Section(f"# Doc\n\n| Item | Value |\n|---|---|\n{rows}", 1)], max_chars=200)
    assert len(docs) > 1
    for d in docs:
        assert len(d.page_content) <= 200
        assert d.page_content.startswith("Doc\n\n| Item | Value |\n|---|---|\n| item")
