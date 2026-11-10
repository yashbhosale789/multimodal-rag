from typing import TypedDict

from langchain_core.documents import Document


class RAGState(TypedDict, total=False):
    question: (
        str  # the user's words; never modified, so we always answer what was asked
    )
    blocked: bool  # guard: the question looked like a prompt injection; the graph ends immediately
    search_query: str  # what retrieval uses; the rewrite node replaces it
    documents: list[
        Document
    ]  # overwritten, not appended: the grader must be able to drop items
    complete: bool  # grader: relevant documents answer every part; false -> web supplements them
    needs_current: (
        bool  # grader: asks for latest/current info -> web even if documents match
    )
    needs_sources: (
        bool  # grader: false for greetings/general knowledge -> answer from the model
    )
    retries: int  # incremented only by the rewrite node; the edge after grading caps it
    generation: str
    removed_citations: list[
        int
    ]  # [n] the model cited that didn't exist: a free hallucination signal
    sources: list[
        str
    ]  # badge label set by attribute, e.g. ["Document + Web"] or ["Model knowledge"]
    citations: list[
        dict
    ]  # derived from the final graded documents, so it can't cite rejected ones
