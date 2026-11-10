import json
import logging

import pytest
from langchain_core.documents import Document

from app.agent import nodes
from app.governance.pii import mask_pii, mask_trace_data
from app.observability import JsonFormatter


@pytest.mark.parametrize("text, expected", [
    ("Mail daniel.reyes@zentrix.example now", "Mail [EMAIL] now"),
    ("Call +1-555-0142.", "Call [PHONE]."),
    ("Call +1‑555‑0142.", "Call [PHONE]."),  # non-breaking hyphens, as gpt-oss actually wrote them
    ("Call (020) 7946 0958", "Call [PHONE]"),
    ("Effective 2026-09-01, output 18,000 t in FY2024 at 7.4%", "Effective 2026-09-01, output 18,000 t in FY2024 at 7.4%"),
])
def test_mask_pii(text, expected):
    assert mask_pii(text) == expected


def test_trace_mask_keeps_structure():
    data = {"messages": [{"content": "reach me at a@b.example"}], "n": 3}
    assert mask_trace_data(data=data) == {"messages": [{"content": "reach me at [EMAIL]"}], "n": 3}


def test_answer_and_log_are_masked():
    doc = Document("contact", metadata={"doc_id": "z" * 64, "source": "z.docx", "section": "Contacts"})
    out = nodes.attribute({"generation": "Email daniel.reyes@zentrix.example [1]", "documents": [doc]})
    assert out["generation"] == "Email [EMAIL] [1]"

    record = logging.LogRecord("app.requests", logging.INFO, "", 0, "chat", None, None)
    record.fields = {"question": "my phone is +44 20 7946 0958"}
    assert json.loads(JsonFormatter().format(record))["question"] == "my phone is [PHONE]"
