from functools import cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec

from app.config import settings


@cache
def get_index():
    pc = Pinecone(api_key=settings.pinecone_api_key)
    if not pc.has_index(settings.pinecone_index):
        pc.create_index(
            name=settings.pinecone_index,
            dimension=settings.embedding_dim,
            metric="cosine",  # truncated Gemini vectors aren't unit-length; cosine ignores length
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    return pc.Index(settings.pinecone_index)


@cache
def get_vector_store() -> PineconeVectorStore:
    embeddings = GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.google_api_key,
        output_dimensionality=settings.embedding_dim,
    )
    return PineconeVectorStore(index=get_index(), embedding=embeddings)


def document_exists(doc_id: str) -> bool:
    return any(get_index().list(prefix=f"{doc_id}#", limit=1))


def delete_document(doc_id: str) -> None:
    # shortcut: docs are shared across users (same file = same IDs); use per-user namespaces if multi-tenancy is needed.
    index = get_index()
    for ids in index.list(prefix=f"{doc_id}#"):
        index.delete(ids=ids)
