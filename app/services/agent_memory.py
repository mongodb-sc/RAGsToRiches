"""Short-term session buffers and long-term customer memory on Atlas.

Short-term memory is a per-``thread_id`` conversation buffer in
``session_turns``. Long-term memory stores durable customer facts in
``user_memory`` and recalls them with Atlas Vector Search.

MongoDB documentation:
- Vector Search: https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-overview/
- ``$vectorSearch`` stage: https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/
- Pre-filters: https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/#std-label-avs-filter
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import OperationFailure

from app.config import Settings, get_settings
from app.services.database import get_collection
from app.services.security import filter_context_by_role, normalize_role, redact_pii
from app.services.vector_search import embed_text

DEFAULT_TURN_LIMIT = 20
DEFAULT_MEMORY_LIMIT = 5
MEMORY_PROJECTION = {
    "_id": 0,
    "memory_id": 1,
    "customer_id": 1,
    "fact": 1,
    "content": 1,
    "title": 1,
    "source": 1,
    "document_type": 1,
    "clearance_level": 1,
    "created_at": 1,
    "memory_source": 1,
    "metadata": 1,
}


def _cosine(left: list[float], right: list[float]) -> float:
    """Score two embedding vectors when Atlas Vector Search is unavailable."""

    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(a * a for a in left)) or 1.0
    norm_right = math.sqrt(sum(b * b for b in right)) or 1.0
    return dot / (norm_left * norm_right)


def _local_memory_search(
    collection,
    customer_id: str,
    query_vector: list[float],
    limit: int,
) -> list[dict[str, Any]]:
    """Rank stored ``user_memory`` embeddings in application code."""

    documents = list(
        collection.find(
            {"customer_id": customer_id},
            {**MEMORY_PROJECTION, "embedding": 1},
        )
    )
    ranked: list[dict[str, Any]] = []
    for document in documents:
        embedding = document.pop("embedding", None) or []
        hit = dict(document)
        hit.setdefault("content", hit.get("fact"))
        hit["score"] = _cosine(query_vector, embedding)
        ranked.append(hit)
    ranked.sort(key=lambda item: item.get("score") or 0.0, reverse=True)
    return ranked[:limit]


def _now() -> datetime:
    """Return a timezone-aware UTC timestamp for memory documents."""

    return datetime.now(timezone.utc)


def _session_collection(settings: Settings | None = None):
    """Return the short-term conversation collection."""

    resolved = settings or get_settings()
    return get_collection(resolved.session_turns_collection, resolved)


def _memory_collection(settings: Settings | None = None):
    """Return the long-term ``user_memory`` collection."""

    resolved = settings or get_settings()
    return get_collection(resolved.user_memory_collection, resolved)


def ensure_memory_indexes(settings: Settings | None = None) -> None:
    """Create classic indexes used by the session buffer and memory lookups."""

    resolved = settings or get_settings()
    _session_collection(resolved).create_index(
        [("thread_id", ASCENDING), ("timestamp", ASCENDING)]
    )
    _memory_collection(resolved).create_index([("memory_id", ASCENDING)], unique=True)
    _memory_collection(resolved).create_index([("customer_id", ASCENDING)])


def append_session_turn(
    thread_id: str,
    role: str,
    content: str,
    *,
    customer_id: str | None = None,
    user_role: str | None = None,
    execution_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one conversation turn to the short-term buffer for ``thread_id``."""

    document: dict[str, Any] = {
        "turn_id": f"TURN-{uuid4().hex[:12]}",
        "thread_id": thread_id,
        "role": role,
        "content": content,
        "customer_id": customer_id,
        "user_role": user_role,
        "execution_id": execution_id,
        "timestamp": _now(),
    }
    if extra:
        document.update(extra)
    _session_collection().insert_one(document)
    return {key: value for key, value in document.items() if key != "_id"}


def fetch_session_turns(
    thread_id: str,
    *,
    limit: int = DEFAULT_TURN_LIMIT,
    user_role: str | None = None,
) -> list[dict[str, Any]]:
    """Return the most recent short-term turns for a thread, oldest first.

    Tier 1 callers receive PII-redacted turn text so the session buffer
    follows the same governance rules as RAG context.
    """

    cursor = (
        _session_collection()
        .find({"thread_id": thread_id}, {"_id": 0})
        .sort("timestamp", DESCENDING)
        .limit(limit)
    )
    turns = list(reversed(list(cursor)))
    if not user_role:
        return turns
    role = normalize_role(user_role)
    if role != "tier1_support":
        return turns
    sanitized: list[dict[str, Any]] = []
    for turn in turns:
        item = dict(turn)
        if isinstance(item.get("content"), str):
            item["content"] = redact_pii(item["content"])
        sanitized.append(item)
    return sanitized


def store_long_term_memory(
    customer_id: str,
    fact: str,
    *,
    source: str = "agent",
    clearance_level: str = "internal",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Embed and persist a durable customer fact in ``user_memory``."""

    settings = get_settings()
    document: dict[str, Any] = {
        "memory_id": f"MEM-{uuid4().hex[:12]}",
        "customer_id": customer_id,
        "fact": fact,
        "content": fact,
        "title": f"Memory for {customer_id}",
        "source": "user_memory",
        "document_type": "customer_memory",
        "clearance_level": clearance_level,
        "created_at": _now(),
        "memory_source": source,
        "metadata": metadata or {},
        "embedding": embed_text(fact, settings),
    }
    _memory_collection(settings).insert_one(document)
    return {key: value for key, value in document.items() if key not in {"_id", "embedding"}}


def retrieve_long_term_memory(
    customer_id: str,
    query: str,
    *,
    limit: int = DEFAULT_MEMORY_LIMIT,
    user_role: str = "compliance_manager",
) -> list[dict[str, Any]]:
    """Recall cross-session facts with Atlas Vector Search on ``user_memory``.

    ``customer_id`` is applied as a ``$vectorSearch`` pre-filter so one
    customer's memories never leak into another customer's session.
    """

    settings = get_settings()
    collection = _memory_collection(settings)
    query_vector = embed_text(query, settings)
    pipeline = [
        {
            "$vectorSearch": {
                "index": settings.memory_vector_index_name,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": max(40, limit * 8),
                "limit": limit,
                "filter": {"customer_id": {"$eq": customer_id}},
            }
        },
        {
            "$project": {
                **MEMORY_PROJECTION,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]
    try:
        hits = list(collection.aggregate(pipeline))
    except OperationFailure:
        hits = []
    if not hits:
        hits = _local_memory_search(collection, customer_id, query_vector, limit)

    for hit in hits:
        hit.setdefault("source", "user_memory")
        hit.setdefault("content", hit.get("fact"))
        hit.setdefault("clearance_level", "internal")

    return filter_context_by_role(user_role, hits)


def memory_brief(memories: list[dict[str, Any]]) -> str:
    """Render recalled facts as a compact prompt block."""

    if not memories:
        return "No long-term memories were recalled for this customer."
    lines = []
    for index, memory in enumerate(memories, start=1):
        score = memory.get("score")
        score_label = f"{float(score):.4f}" if isinstance(score, (int, float)) else "n/a"
        lines.append(f"[{index}] ({score_label}) {memory.get('fact') or memory.get('content')}")
    return "\n".join(lines)
