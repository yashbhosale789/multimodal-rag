import logging

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from app.config import settings
from app.llm import make_llm
from app.stores.graph import EntityType, RelationType, entity_key, known_entity_names, write_chunk_graph

log = logging.getLogger(__name__)


class Entity(BaseModel):
    name: str
    type: EntityType


class Relation(BaseModel):
    source: str = Field(description="Name of the entity the relation starts from.")
    type: RelationType
    target: str = Field(description="Name of the entity the relation points to.")
    detail: str = Field(default="", description="Short qualifier: the item supplied, or the person's role.")


class Extraction(BaseModel):
    entities: list[Entity]
    relations: list[Relation]


PROMPT = """Extract a knowledge graph from the text below.

Entity types: Organization (companies, agencies), Person, Location (cities, regions, countries, plants,
production lines), Product (materials, components, software).
Relation types:
- SUPPLIES: an organization supplies a product or service to another (source = supplier, target = customer)
- LOCATED_IN: an organization, plant or production line is located in a place
- WORKS_FOR: a person works for an organization (detail = their role)
- OPERATES: an organization operates a plant, production line or product

Entities already in the graph: {known}
If the text refers to one of these by a shorter or different name (e.g. "Zentrix" for "Zentrix Minerals"),
use the existing name exactly. Never merge different organizations that share a word ("Acme Corp" and
"Acme Logistics" are two companies). Extract only facts the text states.

Text:
{text}"""

extractor = make_llm(settings.chat_model, settings.chat_fallback_model, schema=Extraction)


def extract_graph(docs: list[Document], ids: list[str]) -> int:
    """Write each chunk's entities and relations to the graph. Returns how many chunks failed extraction."""
    failed = 0
    for doc, chunk_id in zip(docs, ids):  # sequential: each chunk sees the names earlier chunks added
        prompt = PROMPT.format(known=", ".join(known_entity_names()) or "(none yet)", text=doc.page_content)
        try:
            result = extractor.invoke(prompt)
        except Exception as e:  # skip the chunk: its text is still in the vector index
            log.error("Graph extraction failed for %s: %s", chunk_id, e)
            failed += 1
            continue
        entities, relations = _normalize(result)
        props = {k: v for k, v in doc.metadata.items() if k in ("doc_id", "source", "section", "page")}
        write_chunk_graph(chunk_id, props | {"text": doc.page_content}, entities, relations)
    return failed


def _normalize(result: Extraction) -> tuple[list[dict], list[dict]]:
    entities = {entity_key(e.name): {"key": entity_key(e.name), "name": e.name, "type": e.type} for e in result.entities}
    for r in result.relations:  # models sometimes relate entities they didn't list
        for name in (r.source, r.target):
            entities.setdefault(entity_key(name), {"key": entity_key(name), "name": name, "type": None})
    relations = [
        {"type": r.type, "source": entity_key(r.source), "target": entity_key(r.target), "detail": r.detail}
        for r in result.relations
    ]
    return list(entities.values()), relations
