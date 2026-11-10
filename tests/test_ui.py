from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

HOME = str(Path(__file__).parent.parent / "app" / "ui" / "Home.py")
CHAT = {
    "answer": "Margin was 7.4% [1].",
    "sources": ["Document"],
    "citations": [{"type": "Document", "doc_id": "d" * 64, "source": "r.pdf", "section": "Overview", "page": 1,
                   "refs": [1], "images": ["doc.pdf-0001-06.png"]}],
    "trace_id": "t" * 32,
}


@pytest.fixture
def api(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, json=CHAT, request=httpx.Request("POST", url))

    def fake_get(url, **kwargs):
        calls.append({"get": url})
        return httpx.Response(200, content=PNG, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


PNG = bytes.fromhex(  # a valid 1x1 PNG, so st.image can decode it
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def test_chat_shows_answer_badge_and_keeps_session(api):
    at = AppTest.from_file(HOME, default_timeout=30).run()  # an upper bound: CI runners are slow, passing runs don't wait
    session = at.session_state.session_id

    at.chat_input[0].set_value("margin?").run()
    at.chat_input[0].set_value("again?").run()

    assert [m.markdown[0].value for m in at.chat_message] == ["margin?", CHAT["answer"], "again?", CHAT["answer"]]
    assert {c["json"]["session_id"] for c in api if "json" in c} == {session}  # same id on every turn
    image_url = f"/images/{'d' * 64}/doc.pdf-0001-06.png"
    assert sum(image_url in c.get("get", "") for c in api) == 1  # cached: fetched once across reruns
    assert len(at.get("image")) == 2  # shown under both answers
    assert ":blue-badge[Document]" in [m.value for m in at.markdown]  # st.badge renders as badge markdown


def test_api_down_shows_error_and_stops(monkeypatch):
    def down(url, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", down)
    at = AppTest.from_file(HOME, default_timeout=30).run()
    assert "unreachable" in at.error[0].value and not at.chat_input
