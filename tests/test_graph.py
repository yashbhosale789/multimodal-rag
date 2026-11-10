import pytest
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from app.ingestion import graph_extract
from app.ingestion.graph_extract import Entity, Extraction, Relation
from app.stores import graph


def test_entity_key_merges_case_and_spacing_variants():
    assert graph.entity_key("Zentrix  MINERALS ") == graph.entity_key("zentrix minerals") == "zentrix minerals"


def test_extraction_writes_normalized_graph_and_skips_failed_chunks(monkeypatch):
    def fake_llm(prompt):
        if "broken" in prompt:
            raise ValueError("model returned garbage")
        return Extraction(
            entities=[Entity(name="Halvorsen Fabrication", type="Organization")],
            relations=[Relation(source="Halvorsen Fabrication", type="SUPPLIES", target="Acme  Corp", detail="housings")],
        )

    writes = []
    monkeypatch.setattr(graph_extract, "extractor", RunnableLambda(fake_llm))
    monkeypatch.setattr(graph_extract, "known_entity_names", lambda: ["Acme Corp"])
    monkeypatch.setattr(graph_extract, "write_chunk_graph", lambda *args: writes.append(args))
    docs = [
        Document("Reno sub-assemblies come from Halvorsen.", metadata={"doc_id": "d", "source": "ops.pdf", "section": "S", "page": 1, "uploaded_at": 5}),
        Document("broken chunk", metadata={"doc_id": "d", "source": "ops.pdf", "section": "S"}),
    ]

    failed = graph_extract.extract_graph(docs, ["d#0", "d#1"])

    assert failed == 1 and len(writes) == 1
    chunk_id, props, entities, relations = writes[0]
    assert chunk_id == "d#0" and props["page"] == 1 and "uploaded_at" not in props
    assert {e["key"] for e in entities} == {"halvorsen fabrication", "acme corp"}  # endpoint added, key normalized
    assert relations == [{"type": "SUPPLIES", "source": "halvorsen fabrication", "target": "acme corp", "detail": "housings"}]


class FakeTx:
    def __init__(self):
        self.queries = []

    def run(self, query, **params):
        self.queries.append(query)


def test_relation_type_outside_allowlist_never_reaches_the_query():
    tx = FakeTx()
    evil = {"type": "SUPPLIES]->() DETACH DELETE a //", "source": "a", "target": "b", "detail": ""}
    with pytest.raises(ValueError):
        graph._write_chunk(tx, "d#0", {}, [], [evil])
    assert not any("DETACH DELETE" in q for q in tx.queries)


class FakeDriver:
    def __init__(self, nodes):
        self.nodes, self.params = nodes, None

    def execute_query(self, query, **params):
        self.params = params
        return type("Result", (), {"records": [{"c": n} for n in self.nodes]})()


def test_expand_returns_citable_documents_tagged_as_graph(monkeypatch):
    node = {"chunk_id": "orinda#0", "text": "Head office: Tallinn", "doc_id": "orinda", "source": "o.docx", "section": "Company"}
    driver = FakeDriver([node])
    monkeypatch.setattr(graph, "get_driver", lambda: driver)

    [doc] = graph.expand(["it#3"])

    assert driver.params == {"seed_ids": ["it#3"], "limit": 6}  # seeds and limit are parameters, never query text
    assert doc.id == "orinda#0" and doc.page_content == "Head office: Tallinn"
    assert doc.metadata == {"doc_id": "orinda", "source": "o.docx", "section": "Company", "retrieved_by": "graph"}


def test_allowlisted_relation_type_is_written():
    tx = FakeTx()
    graph._write_chunk(tx, "d#0", {}, [], [{"type": "LOCATED_IN", "source": "a", "target": "b", "detail": ""}])
    assert "MERGE (a)-[r:LOCATED_IN]->(b)" in tx.queries[-1]
