"""Atlas Vector Search, hybrid search, and RAG prompt synthesis.

The primary retrieval path is a raw ``$vectorSearch`` aggregation so the
demo shows the exact Atlas pipeline, including metadata pre-filters for
``product_type`` and ``clearance_level``. Hybrid search combines that
vector path with Atlas Search lexical matching using ``$rankFusion`` when
the cluster supports it, otherwise Reciprocal Rank Fusion in application
code.

MongoDB documentation:
- Vector Search overview: https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-overview/
- ``$vectorSearch`` stage: https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/
- Pre-filters on metadata: https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/#std-label-avs-filter
- ``$rankFusion`` hybrid search: https://www.mongodb.com/docs/manual/reference/operator/aggregation/rankFusion/
- Reciprocal Rank Fusion tutorial: https://www.mongodb.com/docs/atlas/atlas-vector-search/tutorials/reciprocal-rank-fusion/
- Atlas Search ``$search``: https://www.mongodb.com/docs/atlas/atlas-search/aggregation-stages/search/
- LangChain + Atlas: https://www.mongodb.com/docs/atlas/atlas-vector-search/ai-integrations/langchain/
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from openai import OpenAI
from pymongo.errors import OperationFailure

from app.config import Settings, get_settings
from app.services.database import get_collection
from app.services.security import (
    filter_context_by_role,
    normalize_role,
    retrieval_filter_for_role,
)

RRF_K = 60


def _hash_embedding(text: str, dimensions: int) -> list[float]:
    """Build a deterministic unit vector when OpenAI is unavailable.

    Token hashes are projected into a fixed number of buckets. Shared
    tokens therefore land in overlapping dimensions, which is good enough
    for local demos that cannot call the embedding API.
    """

    vector = [0.0] * dimensions
    tokens = re.findall(r"[a-z0-9]{3,}", text.lower())
    if not tokens:
        tokens = ["empty"]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def embed_text(text: str, settings: Settings | None = None) -> list[float]:
    """Embed a query or document with OpenAI, falling back to a local hash."""

    resolved = settings or get_settings()
    if not resolved.openai_api_key:
        return _hash_embedding(text, resolved.embedding_dimensions)

    client = OpenAI(api_key=resolved.openai_api_key)
    response = client.embeddings.create(
        model=resolved.openai_embedding_model,
        input=text,
        dimensions=resolved.embedding_dimensions,
    )
    return list(response.data[0].embedding)


def build_vector_search_filter(
    *,
    product_type: str | None = None,
    clearance_levels: list[str] | None = None,
    document_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Compose an Atlas Vector Search MQL pre-filter.

    Atlas requires filter fields to be declared as ``filter`` type paths
    on the vector index. Equality and ``$in`` are the operators used here.
    """

    clauses: list[dict[str, Any]] = []
    if product_type:
        clauses.append({"product_type": {"$eq": product_type}})
    if clearance_levels:
        clauses.append({"clearance_level": {"$in": clearance_levels}})
    if document_type:
        clauses.append({"document_type": {"$eq": document_type}})
    if extra:
        clauses.append(extra)

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def build_vector_search_pipeline(
    query_vector: list[float],
    *,
    filters: dict[str, Any] | None = None,
    limit: int | None = None,
    num_candidates: int | None = None,
    index_name: str | None = None,
    path: str = "embedding",
) -> list[dict[str, Any]]:
    """Return a ``$vectorSearch`` aggregation with optional pre-filters.

    See https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/
    ``filter`` must reference fields declared as ``filter`` paths on the
    vector index (``product_type``, ``clearance_level``, ``document_type``).
    """

    settings = get_settings()
    stage: dict[str, Any] = {
        "$vectorSearch": {
            "index": index_name or settings.vector_index_name,
            "path": path,
            "queryVector": query_vector,
            "numCandidates": num_candidates or settings.vector_num_candidates,
            "limit": limit or settings.vector_limit,
        }
    }
    if filters:
        stage["$vectorSearch"]["filter"] = filters

    return [
        stage,
        {
            "$project": {
                "_id": 0,
                "doc_id": 1,
                "title": 1,
                "content": 1,
                "product_type": 1,
                "clearance_level": 1,
                "document_type": 1,
                "source": 1,
                "customer_id": 1,
                "metadata": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]


def vector_search(
    query: str,
    *,
    product_type: str | None = None,
    user_role: str = "tier1_support",
    document_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Run Atlas Vector Search and apply role-based post filters."""

    settings = get_settings()
    role = normalize_role(user_role)
    role_filter = retrieval_filter_for_role(role)
    clearance_levels = list(role_filter["clearance_level"]["$in"])
    filters = build_vector_search_filter(
        product_type=product_type,
        clearance_levels=clearance_levels,
        document_type=document_type,
    )
    query_vector = embed_text(query, settings)
    pipeline = build_vector_search_pipeline(
        query_vector,
        filters=filters,
        limit=limit,
    )
    collection = get_collection(settings.knowledge_collection, settings)
    hits = list(collection.aggregate(pipeline))
    for hit in hits:
        hit.setdefault("source", "knowledge_base")
    return filter_context_by_role(role, hits)


def _reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    weights: list[float],
    limit: int,
) -> list[dict[str, Any]]:
    """Merge ranked result lists with Reciprocal Rank Fusion."""

    fused: dict[str, dict[str, Any]] = {}
    for results, weight in zip(ranked_lists, weights, strict=True):
        for rank, document in enumerate(results, start=1):
            key = str(document.get("doc_id") or document.get("title") or rank)
            entry = fused.setdefault(
                key,
                {**document, "hybrid_score": 0.0, "vector_score": None, "text_score": None},
            )
            contribution = weight * (1.0 / (RRF_K + rank))
            entry["hybrid_score"] += contribution
            if "score" in document and entry["vector_score"] is None:
                entry["vector_score"] = document.get("score")
            if "text_score" in document:
                entry["text_score"] = document.get("text_score")
    ordered = sorted(fused.values(), key=lambda item: item["hybrid_score"], reverse=True)
    return ordered[:limit]


def _text_search(
    query: str,
    *,
    filters: dict[str, Any] | None,
    limit: int,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Run an Atlas Search lexical query against the knowledge base."""

    must: list[dict[str, Any]] = [
        {"text": {"query": query, "path": ["title", "content"]}}
    ]
    search_filter: list[dict[str, Any]] = []
    if filters:
        for field in ("product_type", "document_type"):
            clause = filters.get(field) if "$and" not in filters else None
            if isinstance(clause, dict) and "$eq" in clause:
                search_filter.append({"equals": {"path": field, "value": clause["$eq"]}})
        clearance = None
        if isinstance(filters.get("clearance_level"), dict):
            clearance = filters["clearance_level"].get("$in")
        elif "$and" in filters:
            for part in filters["$and"]:
                if "clearance_level" in part:
                    clearance = part["clearance_level"].get("$in")
        if clearance:
            search_filter.append(
                {"in": {"path": "clearance_level", "value": clearance}}
            )

    compound: dict[str, Any] = {"must": must}
    if search_filter:
        compound["filter"] = search_filter

    pipeline = [
        {"$search": {"index": settings.text_index_name, "compound": compound}},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "doc_id": 1,
                "title": 1,
                "content": 1,
                "product_type": 1,
                "clearance_level": 1,
                "document_type": 1,
                "source": 1,
                "metadata": 1,
                "text_score": {"$meta": "searchScore"},
            }
        },
    ]
    collection = get_collection(settings.knowledge_collection, settings)
    hits = list(collection.aggregate(pipeline))
    for hit in hits:
        hit.setdefault("source", "knowledge_base")
    return hits


def hybrid_search(
    query: str,
    *,
    product_type: str | None = None,
    user_role: str = "tier1_support",
    document_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Combine vector and lexical search with ``$rankFusion`` or RRF."""

    settings = get_settings()
    role = normalize_role(user_role)
    top_k = limit or settings.vector_limit
    role_filter = retrieval_filter_for_role(role)
    clearance_levels = list(role_filter["clearance_level"]["$in"])
    filters = build_vector_search_filter(
        product_type=product_type,
        clearance_levels=clearance_levels,
        document_type=document_type,
    )
    query_vector = embed_text(query, settings)

    vector_stage: dict[str, Any] = {
        "$vectorSearch": {
            "index": settings.vector_index_name,
            "path": "embedding",
            "queryVector": query_vector,
            "numCandidates": settings.vector_num_candidates,
            "limit": max(top_k, 10),
        }
    }
    if filters:
        vector_stage["$vectorSearch"]["filter"] = filters

    text_compound: dict[str, Any] = {
        "must": [{"text": {"query": query, "path": ["title", "content"]}}]
    }
    if clearance_levels:
        text_compound["filter"] = [
            {"in": {"path": "clearance_level", "value": clearance_levels}}
        ]

    rank_fusion_pipeline = [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "vectorPipeline": [vector_stage],
                        "textPipeline": [
                            {
                                "$search": {
                                    "index": settings.text_index_name,
                                    "compound": text_compound,
                                }
                            },
                            {"$limit": max(top_k, 10)},
                        ],
                    }
                },
                "combination": {
                    "weights": {
                        "vectorPipeline": settings.hybrid_vector_weight,
                        "textPipeline": settings.hybrid_text_weight,
                    }
                },
                "scoreDetails": True,
            }
        },
        {"$limit": top_k},
        {
            "$project": {
                "_id": 0,
                "doc_id": 1,
                "title": 1,
                "content": 1,
                "product_type": 1,
                "clearance_level": 1,
                "document_type": 1,
                "source": 1,
                "metadata": 1,
                "score": {"$meta": "score"},
                "score_details": {"$meta": "scoreDetails"},
            }
        },
    ]

    collection = get_collection(settings.knowledge_collection, settings)
    try:
        hits = list(collection.aggregate(rank_fusion_pipeline))
        for hit in hits:
            hit.setdefault("source", "knowledge_base")
            details = hit.get("score_details")
            if isinstance(details, dict):
                hit["hybrid_score"] = details.get("value", hit.get("score"))
                for pipeline_score in details.get("details") or []:
                    if pipeline_score.get("inputPipelineName") == "vectorPipeline":
                        hit["vector_score"] = pipeline_score.get("value")
            if hit.get("score") is None:
                hit["score"] = hit.get("hybrid_score") or hit.get("vector_score")
        return filter_context_by_role(role, hits)
    except OperationFailure:
        vector_hits = list(
            collection.aggregate(
                build_vector_search_pipeline(query_vector, filters=filters, limit=top_k * 2)
            )
        )
        try:
            text_hits = _text_search(query, filters=filters, limit=top_k * 2, settings=settings)
        except OperationFailure:
            text_hits = []
        fused = _reciprocal_rank_fusion(
            [vector_hits, text_hits] if text_hits else [vector_hits],
            [settings.hybrid_vector_weight, settings.hybrid_text_weight]
            if text_hits
            else [1.0],
            top_k,
        )
        for hit in fused:
            hit.setdefault("source", "knowledge_base")
        return filter_context_by_role(role, fused)


def synthesize_prompt(question: str, chunks: list[dict[str, Any]], user_role: str) -> str:
    """Build a grounded chat prompt from retrieved Atlas context."""

    settings = get_settings()
    role = normalize_role(user_role)
    if not chunks:
        context_block = "No authorized knowledge-base passages were retrieved."
    else:
        parts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            score = chunk.get("score")
            score_label = f"{float(score):.4f}" if isinstance(score, (int, float)) else "n/a"
            title = chunk.get("title") or chunk.get("doc_id") or f"Passage {index}"
            content = str(chunk.get("content") or "").strip()
            parts.append(
                f"[{index}] {title} (vector_score={score_label}, "
                f"clearance={chunk.get('clearance_level')}, "
                f"product={chunk.get('product_type')})\n{content}"
            )
        context_block = "\n\n".join(parts)

    return (
        f"You are a retail banking assistant for {settings.bank_name}. "
        "Answers must be grounded in the retrieved MongoDB Atlas context. "
        "Cite supporting passages as [1], [2], and so on. "
        "If the context is insufficient or redacted, say so clearly. "
        "Do not invent account balances, SSNs, or policy clauses.\n\n"
        f"Caller role: {role}\n\n"
        f"Context:\n{context_block}\n\n"
        f"Question: {question}\n"
    )


def generate_answer(question: str, chunks: list[dict[str, Any]], user_role: str) -> str:
    """Call the chat model, or extractively stitch an answer if no API key."""

    settings = get_settings()
    prompt = synthesize_prompt(question, chunks, user_role)
    if not settings.openai_api_key:
        if not chunks:
            return (
                "No authorized passages were retrieved for this role. "
                "A compliance manager can see restricted transcripts and account metadata."
            )
        summaries = []
        for index, chunk in enumerate(chunks, start=1):
            snippet = str(chunk.get("content") or "")[:280].rsplit(" ", 1)[0]
            summaries.append(f"[{index}] {chunk.get('title')}: {snippet}...")
        return "Based on Atlas-retrieved policy context:\n\n" + "\n\n".join(summaries)

    client = OpenAI(api_key=settings.openai_api_key)
    completion = client.chat.completions.create(
        model=settings.openai_chat_model,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise retail banking assistant. "
                    "Use only the supplied Atlas context and cite sources."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    return (completion.choices[0].message.content or "").strip()


def langchain_vector_store():
    """Optional LangChain wrapper around the same Atlas Vector Search index."""

    from langchain_mongodb import MongoDBAtlasVectorSearch
    from langchain_openai import OpenAIEmbeddings

    settings = get_settings()
    embeddings = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key or None,
        dimensions=settings.embedding_dimensions,
    )
    return MongoDBAtlasVectorSearch(
        collection=get_collection(settings.knowledge_collection, settings),
        embedding=embeddings,
        index_name=settings.vector_index_name,
        text_key="content",
        embedding_key="embedding",
        relevance_score_fn="cosine",
    )


def rag_chat(
    question: str,
    *,
    user_role: str = "tier1_support",
    product_type: str | None = None,
    search_mode: str = "hybrid",
    limit: int | None = None,
) -> dict[str, Any]:
    """Retrieve context, synthesize a prompt, and generate a cited answer."""

    if search_mode == "vector":
        chunks = vector_search(
            question,
            product_type=product_type,
            user_role=user_role,
            limit=limit,
        )
    else:
        chunks = hybrid_search(
            question,
            product_type=product_type,
            user_role=user_role,
            limit=limit,
        )

    answer = generate_answer(question, chunks, user_role)
    citations = [
        {
            "index": index,
            "doc_id": chunk.get("doc_id"),
            "title": chunk.get("title"),
            "score": chunk.get("vector_score") or chunk.get("score") or chunk.get("hybrid_score"),
            "vector_score": chunk.get("vector_score") or chunk.get("score"),
            "clearance_level": chunk.get("clearance_level"),
            "product_type": chunk.get("product_type"),
            "document_type": chunk.get("document_type"),
            "source": chunk.get("source"),
            "redacted": chunk.get("redacted", False),
        }
        for index, chunk in enumerate(chunks, start=1)
    ]
    return {
        "answer": answer,
        "citations": citations,
        "chunks": chunks,
        "prompt": synthesize_prompt(question, chunks, user_role),
        "role": normalize_role(user_role),
        "search_mode": search_mode,
    }
