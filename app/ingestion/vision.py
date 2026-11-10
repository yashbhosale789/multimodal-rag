import base64
import logging
import mimetypes
import re
from pathlib import Path

from langchain_core.messages import HumanMessage

from app.config import settings
from app.ingestion.parsers import Section
from app.llm import make_llm

log = logging.getLogger(__name__)

IMAGE_TAG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

PROMPT = """Describe this image from a business document so it can be found by search and used to answer questions.
- State the image type (bar chart, pie chart, diagram, photo, ...) and its title.
- Transcribe ALL visible text, numbers, labels and legend entries exactly.
- For charts, list every data point as "label: value".
- For diagrams, describe the flow or relationships in order (A -> B -> C).
- Do not guess beyond what is visible. Plain text, no Markdown."""


def add_captions(sections: list[Section]) -> list[str]:
    """Write a description under every image tag, in place. Returns the image paths that failed."""
    paths = list(dict.fromkeys(m.group(1) for s in sections for m in IMAGE_TAG.finditer(s.text)))
    if not paths:
        return []

    llm = make_llm(settings.vision_model, settings.vision_fallback_model)
    results = llm.batch([_message(Path(p)) for p in paths], config={"max_concurrency": 3}, return_exceptions=True)

    captions, failed = {}, []
    for path, result in zip(paths, results):
        if isinstance(result, Exception):
            log.error("Captioning failed for %s: %s", path, result)
            failed.append(path)
        else:
            log.info("Captioned %s with %s", path, result.response_metadata.get("model_name"))
            captions[path] = re.sub(r"\n\s*\n", "\n", result.text.strip())  # no blank lines: chunker splits on them

    for s in sections:
        s.text = IMAGE_TAG.sub(lambda m: _tag(m.group(1), captions.get(m.group(1))), s.text)
    return failed


def _message(path: Path) -> list[HumanMessage]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    image = base64.b64encode(path.read_bytes()).decode()
    return [HumanMessage(content=[
        {"type": "text", "text": PROMPT},
        {"type": "image", "base64": image, "mime_type": mime},
    ])]


def _tag(path: str, caption: str | None) -> str:
    tag = f"![image]({path})"
    return f"{tag}\nImage description: {caption}" if caption else tag
