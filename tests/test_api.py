import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from app.api import main
from app.observability import JsonFormatter

client = TestClient(main.app)


@pytest.fixture
def no_ingest(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "ingest", lambda name, data: calls.append(name) or {"status": "ingested"})
    return calls


def test_upload_accepts_real_pdf(no_ingest):
    r = client.post("/upload", files={"file": ("report.pdf", b"%PDF-1.7 ...")})
    assert r.status_code == 200 and no_ingest == ["report.pdf"]


@pytest.mark.parametrize("name, data", [
    ("virus.exe", b"MZ..."),        # wrong extension
    ("virus.pdf", b"MZ..."),        # renamed: extension says PDF, bytes don't
    ("notes.docx", b"%PDF-1.7"),    # mismatched signature
])
def test_upload_rejects_wrong_type(no_ingest, name, data):
    assert client.post("/upload", files={"file": (name, data)}).status_code == 415
    assert no_ingest == []


def test_upload_rejects_oversized_file(no_ingest, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    assert client.post("/upload", files={"file": ("big.pdf", b"%PDF" + b"x" * 20)}).status_code == 413


def test_delete_blocks_path_traversal(monkeypatch):
    removed = []
    monkeypatch.setattr(main, "remove_document", removed.append)
    assert client.delete("/documents/..%2F..%2Fapp").status_code in (404, 422)
    assert client.delete("/documents/" + "a" * 64).status_code == 200
    assert removed == ["a" * 64]


DOC = "c" * 64


@pytest.fixture
def image_store(tmp_path, monkeypatch):
    (tmp_path / DOC).mkdir()
    (tmp_path / DOC / "doc.pdf-0001-06.png").write_bytes(b"\x89PNG fake")
    (tmp_path / DOC / ".secret.png").write_bytes(b"dotfile")
    (tmp_path / DOC / "notes.txt").write_bytes(b"not an image")
    (tmp_path.parent / "outside.png").write_bytes(b"outside the store")
    monkeypatch.setattr(main, "IMAGE_ROOT", tmp_path)


def test_image_is_served_with_nosniff(image_store):
    r = client.get(f"/images/{DOC}/doc.pdf-0001-06.png")
    assert r.status_code == 200 and r.content == b"\x89PNG fake"
    assert r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", [
    f"/images/{DOC}/..%2F..%2Foutside.png",       # encoded traversal
    f"/images/{DOC}/..%5C..%5Coutside.png",       # encoded Windows traversal
    f"/images/{DOC}/%2Fetc%2Fpasswd",             # absolute path
    "/images/..%2F..%2F/outside.png",              # traversal in the doc_id part
    f"/images/{DOC}/.secret.png",                 # dotfile
    f"/images/{DOC}/notes.txt",                   # not an image type
    f"/images/{DOC}/missing.png",                 # doesn't exist
    f"/images/{DOC}/..",                          # directory
])
def test_image_rejects_every_escape_with_404(image_store, path):
    assert client.get(path).status_code == 404


def test_chat_rejects_empty_question():
    assert client.post("/chat", json={"question": ""}).status_code == 422


def test_session_id_cannot_forge_log_lines():
    forged = 'abc\n{"level": "INFO", "msg": "admin login"}'
    assert client.post("/chat", json={"question": "q", "session_id": forged}).status_code == 422
    assert client.delete("/documents/" + "a" * 64, headers={"X-Session-Id": "a b"}).status_code == 422


def _audit_entries(caplog):
    return [r.fields for r in caplog.records if r.name == "app.audit"]


def test_upload_audits_accepted_and_rejected_attempts(no_ingest, caplog):
    client.post("/upload", files={"file": ("report.pdf", b"%PDF-1.7")}, headers={"X-Session-Id": "u1"})
    client.post("/upload", files={"file": ("virus.pdf", b"MZ...")}, headers={"X-Session-Id": "u2"})

    accepted, rejected = _audit_entries(caplog)
    assert accepted == {"session_id": "u1", "filename": "report.pdf", "bytes": 8, "status": "ingested"}
    assert rejected["session_id"] == "u2" and rejected["status"] == "rejected" and "PDF" in rejected["reason"]


def test_delete_is_audited(monkeypatch, caplog):
    monkeypatch.setattr(main, "remove_document", lambda doc_id: None)
    client.delete("/documents/" + "b" * 64, headers={"X-Session-Id": "u3"})
    assert _audit_entries(caplog) == [{"session_id": "u3", "doc_id": "b" * 64}]


def _request_log(caplog):
    [record] = [r for r in caplog.records if r.name == "app.requests"]
    return record


def test_chat_returns_trace_id_and_logs_one_json_line(monkeypatch, caplog):
    chunk = Document("Margin 7.4%", id="abc#0", metadata={"score": 0.71})
    answer = {"generation": "7.4% [1]", "sources": ["Document"], "citations": [], "documents": [chunk]}
    monkeypatch.setattr(main, "graph", RunnableLambda(lambda state: answer))

    body = client.post("/chat", json={"question": "margin?", "session_id": "s1"}).json()

    line = json.loads(JsonFormatter().format(_request_log(caplog)))
    assert set(body) == {"answer", "sources", "citations", "trace_id"}
    assert len(body["trace_id"]) == 32 and line["trace_id"] == body["trace_id"]  # exists even with tracing off
    assert line["chunks"] == [{"id": "abc#0", "score": 0.71}]
    assert line["session_id"] == "s1" and line["error"] is None and line["latency_ms"] >= 0


def test_chat_failure_is_still_logged(monkeypatch, caplog):
    def broken(state):
        raise RuntimeError("all providers down")

    monkeypatch.setattr(main, "graph", RunnableLambda(broken))

    with pytest.raises(RuntimeError):
        client.post("/chat", json={"question": "margin?"})

    assert "all providers down" in _request_log(caplog).fields["error"]
