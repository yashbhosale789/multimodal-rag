import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agent import nodes

DOC = Document("Acme margin 7.4%")


def test_grade_keeps_only_valid_unique_indexes(monkeypatch):
    docs = [Document("a"), Document("b"), Document("c")]
    fake = nodes.Grade(relevant=[2, 0, 2, 7, -1], complete=True, needs_current=False, needs_sources=True)
    monkeypatch.setattr(nodes, "grader", RunnableLambda(lambda prompt: fake))

    update = nodes.grade({"question": "q", "documents": docs})

    assert [d.page_content for d in update["documents"]] == ["c", "a"]
    assert update["needs_sources"] is True and update["complete"] is True


def test_grade_drops_chunks_when_no_sources_are_needed(monkeypatch):
    fake = nodes.Grade(relevant=[0], complete=True, needs_current=False, needs_sources=False)
    monkeypatch.setattr(nodes, "grader", RunnableLambda(lambda prompt: fake))

    update = nodes.grade({"question": "What is a lithium-ion battery?", "documents": [Document("Acme's packs")]})

    assert update["documents"] == []  # -> generate uses the model-knowledge prompt, badge "Model knowledge"


@pytest.mark.parametrize("state, expected", [
    ({"needs_sources": False, "needs_current": False, "documents": [], "complete": False}, "generate"),
    ({"needs_sources": True, "needs_current": True, "documents": [DOC], "complete": True}, "web_search"),
    ({"needs_sources": True, "needs_current": False, "documents": [DOC], "complete": True}, "generate"),
    ({"needs_sources": True, "needs_current": False, "documents": [DOC], "complete": False}, "web_search"),
    ({"needs_sources": True, "needs_current": False, "documents": [], "complete": False}, "rewrite"),
    ({"needs_sources": True, "needs_current": False, "documents": [], "complete": False, "retries": 1}, "web_search"),
])
def test_after_grade_routes(state, expected):
    assert nodes.after_grade(state) == expected


@pytest.mark.parametrize("score, blocked", [(0.9996, True), (0.0005, False), (None, False)])  # None = guard down
def test_guard_blocks_only_confident_injections(monkeypatch, score, blocked):
    monkeypatch.setattr(nodes, "injection_score", lambda text: score)

    update = nodes.guard({"question": "q"})

    assert update["blocked"] is blocked
    assert nodes.after_guard(update) == ("blocked" if blocked else "retrieve")
    if blocked:
        assert update["sources"] == ["Blocked"] and update["generation"] == nodes.REFUSAL


class FakeVectorStore:
    def similarity_search_with_score(self, query, k):
        return [(Document("hop 1: Orinda goes live", id="it#3"), 0.81)]


def test_retrieve_adds_graph_chunks_expanded_from_the_vector_hits(monkeypatch):
    seeds = []
    hop2 = Document("Orinda's head office is in Tallinn", id="orinda#0", metadata={"retrieved_by": "graph"})
    monkeypatch.setattr(nodes, "get_vector_store", lambda: FakeVectorStore())
    monkeypatch.setattr(nodes, "expand", lambda ids: seeds.extend(ids) or [hop2])

    docs = nodes.retrieve({"question": "q"})["documents"]

    assert seeds == ["it#3"]  # seeds are the raw vector hits, not what the grader keeps
    assert [d.id for d in docs] == ["it#3", "orinda#0"] and docs[0].metadata["score"] == 0.81


def test_retrieve_falls_back_to_vector_hits_when_the_graph_is_down(monkeypatch):
    def down(ids):
        raise ConnectionError("neo4j unreachable")

    monkeypatch.setattr(nodes, "get_vector_store", lambda: FakeVectorStore())
    monkeypatch.setattr(nodes, "expand", down)

    assert [d.id for d in nodes.retrieve({"question": "q"})["documents"]] == ["it#3"]


def test_rewrite_sets_query_and_counts_the_retry(monkeypatch):
    monkeypatch.setattr(nodes, "llm", RunnableLambda(lambda prompt: AIMessage(" acme FY2024 operating margin ")))

    assert nodes.rewrite({"question": "q"}) == {"search_query": "acme FY2024 operating margin", "retries": 1}


def test_web_search_appends_to_graded_documents(monkeypatch):
    class FakeTavily:
        def search(self, query, **kwargs):
            return {"results": [{"title": "Lithium price", "content": "USD 9,000/t", "url": "https://x.example"}]}

    monkeypatch.setattr(nodes, "tavily", FakeTavily())

    docs = nodes.web_search({"question": "q", "documents": [DOC]})["documents"]

    assert docs[0] is DOC and docs[1].metadata == {"url": "https://x.example", "title": "Lithium price", "score": None}


META = {"doc_id": "d" * 64, "source": "r.pdf", "section": "Overview", "page": 1.0}
CHART = "![image](data/images/" + "d" * 64 + "/doc.pdf-0001-06.png)\nImage description: bar chart"
PAGE1_A = Document(f"a\n\n{CHART}", metadata=META)
PAGE1_B = Document(f"b\n\n{CHART}", metadata=META)  # same figure again: listed once
WEB = Document("w", metadata={"url": "https://x.example", "title": "X"})


def test_attribute_groups_same_page_and_keeps_text():
    out = nodes.attribute({"generation": "Margin 7.4% [1][2], peers 5% [3].", "documents": [PAGE1_A, PAGE1_B, WEB]})
    assert out["generation"] == "Margin 7.4% [1][2], peers 5% [3]."
    assert out["citations"] == [
        {"type": "Document", "doc_id": "d" * 64, "source": "r.pdf", "section": "Overview", "page": 1,
         "refs": [1, 2], "images": ["doc.pdf-0001-06.png"]},
        {"type": "Web", "title": "X", "url": "https://x.example", "refs": [3], "images": []},
    ]
    assert out["sources"] == ["Document + Web"]


def test_attribute_strips_hallucinated_citation():
    out = nodes.attribute({"generation": "Margin 7.4% [1][7].", "documents": [PAGE1_A]})
    assert out["generation"] == "Margin 7.4% [1]."
    assert [c["refs"] for c in out["citations"]] == [[1]]
    assert out["removed_citations"] == [7]


def test_attribute_accepts_fullwidth_citations_and_normalizes_them():
    out = nodes.attribute({"generation": "Price 75,000 CNY【1】.", "documents": [WEB]})
    assert out["generation"] == "Price 75,000 CNY[1]." and out["sources"] == ["Web"]


def test_attribute_uncited_answer_lists_all_and_says_so():
    out = nodes.attribute({"generation": "Margin is 7.4%.", "documents": [PAGE1_A, WEB]})
    assert len(out["citations"]) == 2 and out["sources"] == ["Document + Web (uncited)"]


def test_attribute_model_knowledge_strips_stray_tags():
    out = nodes.attribute({"generation": "Batteries store energy [1].", "documents": []})
    assert out == {
        "generation": "Batteries store energy .",
        "citations": [],
        "sources": ["Model knowledge"],
        "removed_citations": [1],
    }


def test_web_search_failure_keeps_state_unchanged(monkeypatch):
    class DownTavily:
        def search(self, query, **kwargs):
            raise ConnectionError("down")

    monkeypatch.setattr(nodes, "tavily", DownTavily())

    assert nodes.web_search({"question": "q", "documents": [DOC]}) == {}
