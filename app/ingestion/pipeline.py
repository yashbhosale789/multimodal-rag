import hashlib
import shutil
import tempfile
import time
from pathlib import Path

from app.ingestion.chunking import chunk
from app.ingestion.graph_extract import extract_graph
from app.ingestion.parsers import parse
from app.ingestion.vision import add_captions
from app.stores.graph import delete_graph_document
from app.stores.vector import delete_document, document_exists, get_vector_store

IMAGE_ROOT = Path("data/images")


def ingest(filename: str, data: bytes) -> dict:
    doc_id = hashlib.sha256(data).hexdigest()
    result = {"doc_id": doc_id, "source": filename}
    if document_exists(
        doc_id
    ):  # identical bytes are already indexed; reprocess = DELETE then upload
        return result | {"status": "already_ingested"}

    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = (
                Path(tmp) / f"doc{Path(filename).suffix.lower()}"
            )  # our name, never the user's
            path.write_bytes(data)
            sections = parse(path, IMAGE_ROOT / doc_id)
        failed = add_captions(sections)
        docs = chunk(sections)
        if not docs:
            raise ValueError("No extractable text (scanned PDFs are not supported)")

        uploaded_at = int(
            time.time()
        )  # a number, so Pinecone range filters ($gte) work
        for d in docs:
            d.metadata |= {
                "doc_id": doc_id,
                "source": filename,
                "uploaded_at": uploaded_at,
            }
        ids = [f"{doc_id}#{i}" for i in range(len(docs))]
        get_vector_store().add_documents(docs, ids=ids)
        graph_failed = extract_graph(docs, ids)  # same chunk IDs: graph facts cite vector chunks
    except Exception:  # includes Neo4j being down: both stores must hold the document, or neither
        remove_document(
            doc_id
        )  # a half-written doc would look "already ingested" and never be retried
        raise

    return result | {
        "status": "ingested",
        "chunks": len(docs),
        "failed_images": [Path(p).name for p in failed],
        "graph_failed_chunks": graph_failed,
    }


def remove_document(doc_id: str) -> None:
    delete_document(doc_id)
    shutil.rmtree(IMAGE_ROOT / doc_id, ignore_errors=True)
    delete_graph_document(doc_id)  # last: if Neo4j is down, vectors and images are already gone
