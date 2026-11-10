import base64

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.ingestion import vision
from app.ingestion.parsers import Section


def fake_llm(messages):
    image = base64.b64decode(messages[0].content[1]["base64"])
    if image == b"bad":
        raise ValueError("model down")
    return AIMessage("Bar chart: Q3 2,400")


def test_captions_inserted_and_one_failure_does_not_sink_the_rest(tmp_path, monkeypatch):
    good, bad = tmp_path / "good.png", tmp_path / "bad.png"
    good.write_bytes(b"good")
    bad.write_bytes(b"bad")
    monkeypatch.setattr(vision, "make_llm", lambda *models: RunnableLambda(fake_llm))
    sections = [Section(f"Intro\n![]({good.as_posix()})\nMore", 1), Section(f"![]({bad.as_posix()})", 2)]

    failed = vision.add_captions(sections)

    assert failed == [bad.as_posix()]
    assert f"![image]({good.as_posix()})\nImage description: Bar chart: Q3 2,400\nMore" in sections[0].text
    assert sections[1].text == f"![image]({bad.as_posix()})"
