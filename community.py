"""Embedding, community detection (KNN+WCC), and entity resolution via Gemini."""

from typing import List, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from retry import retry

from langchain_community.vectorstores import Neo4jVector
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from graphdatascience import GraphDataScience
from pydantic import BaseModel, Field

import config
import db


# ── Pydantic models for structured Gemini output ──

class DuplicateEntities(BaseModel):
    entities: List[str] = Field(
        description="Entities that represent the same object or real-world entity and should be merged"
    )


class Disambiguate(BaseModel):
    merge_entities: Optional[List[DuplicateEntities]] = Field(
        description="Lists of entities that represent the same object or real-world entity and should be merged"
    )


# ── Prompts ──

_SYSTEM_PROMPT = """You are a data processing assistant. Your task is to identify duplicate entities in a list and decide which of them should be merged.
The entities might be slightly different in format or content, but essentially refer to the same thing. Use your analytical skills to determine duplicates.

Here are the rules for identifying duplicates:
1. Entities with minor typographical differences should be considered duplicates.
2. Entities with different formats but the same content should be considered duplicates.
3. Entities that refer to the same real-world object or concept, even if described differently, should be considered duplicates.
4. If it refers to different numbers, dates, or products, do not merge results
"""

_USER_TEMPLATE = """
Here is the list of entities to process:
{entities}

Please identify duplicates, merge them, and provide the merged list.
"""


def embed_entities():
    """Create embeddings for __Entity__ nodes using HuggingFace multilingual-e5-large."""
    embedding_model = HuggingFaceEmbeddings(
        model_name=config.EMBEDDING_MODEL,
        model_kwargs={"device": config.EMBEDDING_DEVICE},
        encode_kwargs={"normalize_embeddings": True},
        cache_folder=str(config.EMBEDDING_CACHE_DIR),
    )

    Neo4jVector.from_existing_graph(
        embedding=embedding_model,
        url=config.NEO4J_URI,
        username=config.NEO4J_USER,
        password=config.NEO4J_PASSWORD,
        node_label="__Entity__",
        text_node_properties=["id", "description"],
        embedding_node_property="embedding",
    )
    print("[community] Embeddings written to Neo4j.")


def run_community_detection():
    """Project graph, run KNN for similarity, run WCC for communities."""
    gds = GraphDataScience(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
    )

    G, result = gds.graph.project(
        "entities",
        "__Entity__",
        "*",
        nodeProperties=["embedding"],
    )

    gds.knn.mutate(
        G,
        nodeProperties=["embedding"],
        mutateRelationshipType="SIMILAR",
        mutateProperty="score",
        similarityCutoff=config.SIMILARITY_THRESHOLD,
    )

    gds.wcc.write(
        G,
        writeProperty="wcc",
        relationshipTypes=["SIMILAR"],
    )

    print("[community] KNN + WCC community detection complete.")
    return G


def find_duplicate_candidates():
    """Query Neo4j for potential duplicate entity groups using WCC + text distance."""
    graph = db.get_graph()
    candidates = graph.query(
        """MATCH (e:`__Entity__`)
        WHERE size(e.id) > 4 // longer than 4 characters
        WITH e.wcc AS community, collect(e) AS nodes, count(*) AS count
        WHERE count > 1
        UNWIND nodes AS node
        // Add text distance
        WITH distinct
          [n IN nodes WHERE apoc.text.distance(toLower(node.id), toLower(n.id)) < $distance | n.id] AS intermediate_results
        WHERE size(intermediate_results) > 1
        WITH collect(intermediate_results) AS results
        // combine groups together if they share elements
        UNWIND range(0, size(results)-1, 1) as index
        WITH results, index, results[index] as result
        WITH apoc.coll.sort(reduce(acc = result, index2 IN range(0, size(results)-1, 1) |
                CASE WHEN index <> index2 AND
                    size(apoc.coll.intersection(acc, results[index2])) > 0
                    THEN apoc.coll.union(acc, results[index2])
                    ELSE acc
                END
        )) as combinedResult
        WITH distinct(combinedResult) as combinedResult
        // extra filtering
        WITH collect(combinedResult) as allCombinedResults
        UNWIND range(0, size(allCombinedResults)-1, 1) as combinedResultIndex
        WITH allCombinedResults[combinedResultIndex] as combinedResult, combinedResultIndex, allCombinedResults
        WHERE NOT any(x IN range(0,size(allCombinedResults)-1,1)
            WHERE x <> combinedResultIndex
            AND apoc.coll.containsAll(allCombinedResults[x], combinedResult)
        )
        RETURN combinedResult
        """,
        params={"distance": config.WORD_EDIT_DISTANCE},
    )
    print(f"[community] Found {len(candidates)} duplicate candidate groups.")
    return candidates


def resolve_and_merge():
    """
    Full community pipeline: embed -> detect -> find duplicates -> resolve -> merge.

    Resumability: checks if 'wcc' property already exists on __Entity__ nodes.
    """
    graph = db.get_graph()
    G = None

    # ── Resumability checkpoint: check if WCC already ran ──
    wcc_check = graph.query(
        "MATCH (n:`__Entity__`) WHERE n.wcc IS NOT NULL RETURN count(n) AS c LIMIT 1"
    )
    if wcc_check and wcc_check[0]["c"] > 0:
        print("[community] WCC property found on nodes, skipping embed + community detection.")
    else:
        embed_entities()
        G = run_community_detection()

    candidates = find_duplicate_candidates()

    if not candidates:
        print("[community] No duplicates to resolve.")
        if G:
            G.drop()
        return

    # ── Gemini entity resolution ──
    extraction_llm = ChatGoogleGenerativeAI(
        model=config.GEMINI_RESOLUTION_MODEL,
        google_api_key=config.GOOGLE_API_KEY,
    ).with_structured_output(Disambiguate)

    extraction_prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        ("human", _USER_TEMPLATE),
    ])
    extraction_chain = extraction_prompt | extraction_llm

    @retry(tries=3, delay=2)
    def entity_resolution(entities: List[str]) -> Optional[List[List[str]]]:
        return [
            el.entities
            for el in extraction_chain.invoke({"entities": entities}).merge_entities
        ]

    merged_entities = []
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        futures = [
            executor.submit(entity_resolution, el["combinedResult"])
            for el in candidates
        ]
        for future in tqdm(
            as_completed(futures), total=len(futures), desc="Entity resolution"
        ):
            to_merge = future.result()
            if to_merge:
                merged_entities.extend(to_merge)

    print(f"[community] Merging {len(merged_entities)} entity groups...")

    # ── APOC merge ──
    graph.query(
        """
        UNWIND $data AS candidates
        CALL {
          WITH candidates
          MATCH (e:__Entity__) WHERE e.id IN candidates
          RETURN collect(e) AS nodes
        }
        CALL apoc.refactor.mergeNodes(nodes, {properties: { `.*`: 'discard' }})
        YIELD node
        RETURN count(*)
        """,
        params={"data": merged_entities},
    )

    # ── Cleanup ──
    if G:
        G.drop()

    db.refresh_schema()
    db.count_connected_nodes()
