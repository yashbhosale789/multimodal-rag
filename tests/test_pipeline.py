from pathlib import Path

import pytest

from app.ingestion import pipeline

PDF = (Path(__file__).parent.parent / "samples" / "Acme_Annual_Report_2025.pdf").read_bytes()


class FakeStore:
    def __init__(self, fail=False):
        self.fail, self.docs, self.ids = fail, [], []

    def add_documents(self, docs, ids):
        if self.fail:
            raise RuntimeError("embedding API down")
        self.docs, self.ids = docs, ids


@pytest.fixture
def offline(tmp_path, monkeypatch):
    removed = []
    monkeypatch.setattr(pipeline, "IMAGE_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "document_exists", lambda doc_id: False)
    monkeypatch.setattr(pipeline, "add_captions", lambda sections: [])
    monkeypatch.setattr(pipeline, "delete_document", removed.append)
    monkeypatch.setattr(pipeline, "delete_graph_document", removed.append)
    monkeypatch.setattr(pipeline, "extract_graph", lambda docs, ids: 0)
    return removed


def test_ingest_assigns_ids_and_metadata(offline, monkeypatch):
    store, graph_ids = FakeStore(), []
    monkeypatch.setattr(pipeline, "get_vector_store", lambda: store)
    monkeypatch.setattr(pipeline, "extract_graph", lambda docs, ids: graph_ids.extend(ids) or 1)

    result = pipeline.ingest("Report.PDF", PDF)

    doc_id = result["doc_id"]
    assert result["status"] == "ingested" and result["chunks"] == len(store.docs) > 0
    assert store.ids == [f"{doc_id}#{i}" for i in range(len(store.docs))]
    assert graph_ids == store.ids and result["graph_failed_chunks"] == 1  # graph cites the same chunk IDs
    assert all(d.metadata["doc_id"] == doc_id and d.metadata["source"] == "Report.PDF" for d in store.docs)
    assert isinstance(store.docs[0].metadata["uploaded_at"], int)


def test_failed_upsert_cleans_up_so_retry_is_possible(offline, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "get_vector_store", lambda: FakeStore(fail=True))

    with pytest.raises(RuntimeError):
        pipeline.ingest("report.pdf", PDF)

    assert len(offline) == 2  # vectors and graph deleted
    assert not any(tmp_path.iterdir())  # extracted images deleted


def test_identical_file_is_not_reprocessed(monkeypatch):
    monkeypatch.setattr(pipeline, "document_exists", lambda doc_id: True)
    monkeypatch.setattr(pipeline, "parse", lambda *a: pytest.fail("should not parse"))

    assert pipeline.ingest("copy-of-report.pdf", PDF)["status"] == "already_ingested"
