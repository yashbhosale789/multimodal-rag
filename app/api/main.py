import logging
import re
import time
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from langchain_core.callbacks import get_usage_metadata_callback
from langfuse import propagate_attributes
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel, Field

from app.agent.graph import graph
from app.agent.nodes import PROMPT_VERSION
from app.ingestion.pipeline import IMAGE_ROOT, ingest, remove_document
from app.observability import langfuse, setup_logging

setup_logging()
log = logging.getLogger("app.requests")
audit = logging.getLogger("app.audit")  # who uploaded or deleted what; chats are audited by app.requests
app = FastAPI(title="Multimodal Graph RAG API")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
FILE_SIGNATURES = {".pdf": b"%PDF", ".docx": b"PK\x03\x04"}  # the extension must match the real content
DOC_ID = re.compile(r"[0-9a-f]{64}")
IMAGE_NAME = re.compile(r"\w[\w.-]*\.(?:png|jpe?g|gif)")  # no separators, no leading dot, images only


# Client-asserted, unverified: correlation only, not identity (see docs/governance.md).
# The pattern blocks newlines and control characters that could forge log lines.
SESSION_ID = r"^[\w.-]+$"
SessionHeader = Annotated[str | None, Header(max_length=100, pattern=SESSION_ID)]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)  # the injection guard only reads ~512 tokens
    session_id: str | None = Field(default=None, max_length=100, pattern=SESSION_ID)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest) -> dict:  # def, not async: graph.invoke blocks, so FastAPI runs it in a thread
    result = answer(req.question, req.session_id)
    return {
        "answer": result["generation"],
        "sources": result["sources"],
        "citations": result["citations"],
        "trace_id": result["trace_id"],
    }


def answer(question: str, session_id: str | None = None) -> dict:
    """Run the graph under one Langfuse trace and write one JSON log line. Returns the final state + stats."""
    start, result, error = time.perf_counter(), {}, None
    trace_id = langfuse.create_trace_id()  # ours, not Langfuse's: the log keeps it even if tracing is off or down
    with (
        langfuse.start_as_current_observation(
            name="chat", input=question, trace_context={"trace_id": trace_id}
        ) as span,
        propagate_attributes(session_id=session_id, version=PROMPT_VERSION),
        get_usage_metadata_callback() as usage,
    ):
        try:
            result = graph.invoke({"question": question}, config={"callbacks": [CallbackHandler()]})
            span.update(output=result["generation"])
        except Exception as e:
            error = repr(e)
            raise
        finally:  # runs on success and failure: every request gets its log line
            stats = {
                "trace_id": trace_id,
                "latency_ms": round((time.perf_counter() - start) * 1000),
                "tokens_by_model": {m: u.get("total_tokens") for m, u in usage.usage_metadata.items()},
            }
            _log_chat(question, session_id, result, stats, error)
    return result | stats


def _log_chat(question: str, session_id: str | None, result: dict, stats: dict, error: str | None) -> None:
    log.info("chat", extra={"fields": stats | {  # trace_id is the bridge: paste it into Langfuse
        "session_id": session_id,
        "question": question,
        "chunks": [{"id": d.id or d.metadata.get("url"), "score": d.metadata.get("score")}
                   for d in result.get("documents", [])],
        "sources": result.get("sources"),
        "answer": result.get("generation"),
        "removed_citations": result.get("removed_citations"),  # hallucination signal
        "total_tokens": sum(t or 0 for t in stats["tokens_by_model"].values()),  # by-model shows if fallback ran
        "prompt_version": PROMPT_VERSION,
        "error": error,
    }})


@app.post("/upload")
def upload(file: UploadFile, x_session_id: SessionHeader = None) -> dict:
    # shortcut: ingestion runs inside the request (~25 s for our samples); move to BackgroundTasks + status polling once uploads are big enough to hit client timeouts.
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    entry = {"session_id": x_session_id, "filename": file.filename, "bytes": len(data)}
    try:
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File is larger than 20 MB")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in FILE_SIGNATURES or not data.startswith(FILE_SIGNATURES[suffix]):
            raise HTTPException(415, "Only PDF and DOCX files are supported")
        try:
            result = ingest(file.filename, data)
        except ValueError as e:  # e.g. a scanned PDF with no text layer
            raise HTTPException(422, str(e))
        entry |= result
        return result
    except HTTPException as e:  # rejected attempts are the security-relevant ones
        entry |= {"status": "rejected", "reason": e.detail}
        raise
    except Exception as e:
        entry |= {"status": "error", "reason": repr(e)}
        raise
    finally:
        audit.info("upload", extra={"fields": entry})


@app.get("/images/{doc_id}/{filename}")
def image(doc_id: str, filename: str) -> FileResponse:
    root = IMAGE_ROOT.resolve()
    path = (root / doc_id / filename).resolve()  # resolve() follows "..", absolute parts and symlinks
    valid = DOC_ID.fullmatch(doc_id) and IMAGE_NAME.fullmatch(filename)
    if not valid or not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404)  # one answer for every failure: don't tell a prober which check stopped it
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: str, x_session_id: SessionHeader = None) -> dict:
    if not DOC_ID.fullmatch(doc_id):  # doc_id becomes a folder path in remove_document: block "../"
        raise HTTPException(422, "Invalid document id")
    remove_document(doc_id)
    audit.info("delete", extra={"fields": {"session_id": x_session_id, "doc_id": doc_id}})
    return {"doc_id": doc_id, "status": "deleted"}
