from functools import cache
from typing import Literal, get_args

from langchain_core.documents import Document
from neo4j import GraphDatabase

from app.config import settings

EntityType = Literal["Organization", "Person", "Location", "Product"]
RelationType = Literal["SUPPLIES", "LOCATED_IN", "WORKS_FOR", "OPERATES"]
RELATION_TYPES = get_args(RelationType)

# Unique keys make MERGE race-safe under concurrent uploads, and their backing indexes turn
# MERGE's lookup from a label scan into an index seek.
CONSTRAINTS = (
    "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.key IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
)

WRITE_CHUNK = """
MERGE (c:Chunk {chunk_id: $chunk_id}) SET c += $props
WITH c UNWIND $entities AS ent
MERGE (e:Entity {key: ent.key}) ON CREATE SET e.name = ent.name, e.type = ent.type
MERGE (c)-[:MENTIONS]->(e)
"""

# {type} is filled from RELATION_TYPES only: relationship types can't be query parameters.
WRITE_RELATIONS = """
UNWIND $relations AS rel
MATCH (a:Entity {{key: rel.source}}), (b:Entity {{key: rel.target}})
MERGE (a)-[r:{type}]->(b)
ON CREATE SET r.detail = rel.detail, r.chunk_ids = [$chunk_id]
ON MATCH SET r.chunk_ids = CASE WHEN $chunk_id IN r.chunk_ids THEN r.chunk_ids ELSE r.chunk_ids + $chunk_id END
"""


# Seeds are the vector hits. From the entities they mention, follow one relation and return the chunks
# that stated it: the second hop vector search can't reach. Chunks reached through the most specific
# entities (fewest mentions) come first, so hubs like "Acme Corp" rarely use up the limit. Ranking beat a
# fixed hub threshold, which only worked at a cut-off tuned to this corpus.
EXPAND = """
MATCH (seed:Chunk)-[:MENTIONS]->(e:Entity) WHERE seed.chunk_id IN $seed_ids
WITH DISTINCT e, COUNT { (e)<-[:MENTIONS]-() } AS mentions
MATCH (e)-[r]-(:Entity)
UNWIND r.chunk_ids AS chunk_id
WITH chunk_id, min(mentions) AS specificity WHERE NOT chunk_id IN $seed_ids
ORDER BY specificity, chunk_id LIMIT $limit
MATCH (c:Chunk {chunk_id: chunk_id})
RETURN c
"""


def entity_key(name: str) -> str:
    """An entity's identity: "Zentrix  Minerals" and "zentrix minerals" must be the same node."""
    return " ".join(name.lower().split())


@cache
def get_driver():
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    for statement in CONSTRAINTS:  # IF NOT EXISTS: safe on every start
        driver.execute_query(statement)
    return driver


def known_entity_names(limit: int = 300) -> list[str]:
    # shortcut: sends up to 300 names to every extraction prompt; at scale, send only names similar to the chunk's.
    query = "MATCH (e:Entity) RETURN e.name AS name ORDER BY name LIMIT $limit"
    return [r["name"] for r in get_driver().execute_query(query, limit=limit).records]


def write_chunk_graph(chunk_id: str, props: dict, entities: list[dict], relations: list[dict]) -> None:
    """One transaction per chunk: its entities, MENTIONS edges and relations land together or not at all."""
    with get_driver().session() as session:
        session.execute_write(_write_chunk, chunk_id, props, entities, relations)


def _write_chunk(tx, chunk_id: str, props: dict, entities: list[dict], relations: list[dict]) -> None:
    tx.run(WRITE_CHUNK, chunk_id=chunk_id, props=props, entities=entities)
    for rel_type in {r["type"] for r in relations}:
        if rel_type not in RELATION_TYPES:  # this string goes into the query text: allowlist, never trust input
            raise ValueError(f"Unknown relation type: {rel_type!r}")
        batch = [r for r in relations if r["type"] == rel_type]
        tx.run(WRITE_RELATIONS.format(type=rel_type), relations=batch, chunk_id=chunk_id)


def expand(seed_ids: list[str], limit: int = 6) -> list[Document]:
    """Chunks one relation away from the seeds' entities, most specific first, as citable Documents."""
    # 6, not 4: in testing, 4 slots let a hub's chunks crowd out Q14's second hop.
    records = get_driver().execute_query(EXPAND, seed_ids=seed_ids, limit=limit).records
    docs = []
    for record in records:
        props = dict(record["c"])
        text = props.pop("text")
        docs.append(Document(text, id=props.pop("chunk_id"), metadata=props | {"retrieved_by": "graph"}))
    return docs


def delete_graph_document(doc_id: str) -> None:
    prefix = f"{doc_id}#"  # chunk IDs are "<doc_id>#<n>", so the prefix selects one document
    driver = get_driver()
    # shortcut: scans every relationship to find this document's chunk IDs; index chunk IDs on a node if graphs get large.
    driver.execute_query(
        """MATCH (:Entity)-[r]->(:Entity) WHERE any(id IN r.chunk_ids WHERE id STARTS WITH $prefix)
           SET r.chunk_ids = [id IN r.chunk_ids WHERE NOT id STARTS WITH $prefix]
           WITH r WHERE r.chunk_ids = [] DELETE r""",
        prefix=prefix,
    )  # a relation also stated by another document keeps that document's citations
    driver.execute_query("MATCH (c:Chunk) WHERE c.chunk_id STARTS WITH $prefix DETACH DELETE c", prefix=prefix)
    driver.execute_query("MATCH (e:Entity) WHERE NOT (e)--() DELETE e")  # entities no document mentions anymore
