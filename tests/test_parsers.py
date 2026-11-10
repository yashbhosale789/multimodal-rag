from pathlib import Path

from app.ingestion.parsers import parse

SAMPLES = Path(__file__).parent.parent / "samples"


def test_pdf_keeps_pages_tables_and_image_positions(tmp_path):
    sections = parse(SAMPLES / "Acme_Annual_Report_2025.pdf", tmp_path)
    assert [s.page for s in sections] == [1, 2]
    text = "\n".join(s.text for s in sections)
    assert "|Operating margin|6.1%|7.4%|9.8%|" in text
    assert text.count("![](") == 2
    assert len(list(tmp_path.iterdir())) == 2


def test_docx_keeps_title_table_and_image(tmp_path):
    [section] = parse(SAMPLES / "Zentrix_Supplier_Profile.docx", tmp_path)
    assert section.page is None
    assert section.text.startswith("# Zentrix Minerals - Supplier Profile")
    assert "| Valdoria North | Valdoria | 18,000 | Active |" in section.text
    assert section.text.count("![](") == 1
    assert len(list(tmp_path.iterdir())) == 1
