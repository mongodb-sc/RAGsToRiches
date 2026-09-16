"""Audit trail and document-level provenance for agent answers.

Every LangGraph node writes an ``ai_audit_logs`` row. After the final
answer is generated, ``track_provenance`` maps that answer back to the
exact Atlas chunks that grounded it.

MongoDB documentation:
- Aggregation pipeline: https://www.mongodb.com/docs/manual/core/aggregation-pipeline/
- Data modeling: https://www.mongodb.com/docs/manual/core/data-modeling-introduction/
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING

from app.config import Settings, get_settings
from app.services.database import get_collection
from app.services.security import normalize_role


def _now() -> datetime:
    """Return a timezone-aware UTC timestamp for audit documents."""

    return datetime.now(timezone.utc)


def _audit_collection(settings: Settings | None = None):
    """Return the ``ai_audit_logs`` collection."""

    resolved = settings or get_settings()
    return get_collection(resolved.audit_logs_collection, resolved)


def _lineage_collection(settings: Settings | None = None):
    """Return the ``answer_lineage`` collection."""

    resolved = settings or get_settings()
    return get_collection(resolved.lineage_collection, resolved)


def ensure_audit_indexes(settings: Settings | None = None) -> None:
    """Create lookup indexes for execution history and lineage joins."""

    resolved = settings or get_settings()
    _audit_collection(resolved).create_index([("execution_id", ASCENDING)])
    _audit_collection(resolved).create_index(
        [("thread_id", ASCENDING), ("timestamp", ASCENDING)]
    )
    _lineage_collection(resolved).create_index([("execution_id", ASCENDING)])
    _lineage_collection(resolved).create_index([("thread_id", ASCENDING)])


def new_execution_id() -> str:
    """Mint a unique execution identifier for one agent run."""

    return f"EX-{uuid4().hex[:16]}"


def log_agent_step(
    *,
    execution_id: str,
    thread_id: str,
    user_role: str,
    step_name: str,
    tool_called: str,
    tool_input: Any,
    tool_output: Any,
    reasoning_thought: str,
    execution_latency_ms: float,
    customer_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one node/tool execution record to ``ai_audit_logs``."""

    document: dict[str, Any] = {
        "log_id": f"AUD-{uuid4().hex[:12]}",
        "execution_id": execution_id,
        "thread_id": thread_id,
        "timestamp": _now(),
        "user_role": normalize_role(user_role),
        "customer_id": customer_id,
        "step_name": step_name,
        "tool_called": tool_called,
        "tool_input": tool_input,
        "tool_output": tool_output,
        "reasoning_thought": reasoning_thought,
        "execution_latency_ms": round(float(execution_latency_ms), 2),
    }
    if extra:
        document.update(extra)
    _audit_collection().insert_one(document)
    return {key: value for key, value in document.items() if key != "_id"}


def track_provenance(
    *,
    execution_id: str,
    thread_id: str,
    answer: str,
    chunks: list[dict[str, Any]],
    user_role: str,
    customer_id: str | None = None,
    question: str | None = None,
) -> dict[str, Any]:
    """Capture chunk-level lineage from retrieved Atlas documents to the answer.

    Each retrieved passage becomes a lineage row with ``chunk_id``,
    ``source_doc``, ``doc_version``, and the vector similarity score so
    an auditor can reconstruct why the model said what it said.
    """

    retrieved_at = _now()
    records: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        records.append(
            {
                "lineage_id": f"LIN-{uuid4().hex[:12]}",
                "execution_id": execution_id,
                "thread_id": thread_id,
                "customer_id": customer_id,
                "user_role": normalize_role(user_role),
                "question": question,
                "answer": answer,
                "citation_index": index,
                "chunk_id": chunk.get("doc_id") or chunk.get("memory_id") or f"chunk-{index}",
                "source_doc": chunk.get("title") or chunk.get("doc_id"),
                "source": chunk.get("source"),
                "doc_version": (
                    metadata.get("doc_version")
                    or chunk.get("doc_version")
                    or chunk.get("document_type")
                    or "v1"
                ),
                "vector_score": chunk.get("vector_score")
                or chunk.get("score")
                or chunk.get("hybrid_score"),
                "clearance_level": chunk.get("clearance_level"),
                "product_type": chunk.get("product_type"),
                "redacted": chunk.get("redacted", False),
                "content_excerpt": str(chunk.get("content") or "")[:400],
                "created_at": retrieved_at,
            }
        )

    payload = {
        "execution_id": execution_id,
        "thread_id": thread_id,
        "customer_id": customer_id,
        "user_role": normalize_role(user_role),
        "question": question,
        "answer": answer,
        "chunk_count": len(records),
        "chunks": records,
        "created_at": retrieved_at,
    }
    if records:
        _lineage_collection().insert_many(records)
    return payload


def list_audit_logs(
    *,
    execution_id: str | None = None,
    thread_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return audit rows for one execution, one thread, or the latest runs."""

    query: dict[str, Any] = {}
    if execution_id:
        query["execution_id"] = execution_id
    if thread_id:
        query["thread_id"] = thread_id
    return list(
        _audit_collection()
        .find(query, {"_id": 0})
        .sort("timestamp", ASCENDING)
        .limit(limit)
    )


def list_recent_executions(limit: int = 25) -> list[dict[str, Any]]:
    """Return one summary row per recent ``execution_id`` for the audit grid."""

    pipeline = [
        {"$sort": {"timestamp": DESCENDING}},
        {
            "$group": {
                "_id": "$execution_id",
                "execution_id": {"$first": "$execution_id"},
                "thread_id": {"$first": "$thread_id"},
                "customer_id": {"$first": "$customer_id"},
                "user_role": {"$first": "$user_role"},
                "started_at": {"$min": "$timestamp"},
                "ended_at": {"$max": "$timestamp"},
                "steps": {"$sum": 1},
                "total_latency_ms": {"$sum": "$execution_latency_ms"},
                "step_names": {"$push": "$step_name"},
            }
        },
        {"$sort": {"ended_at": DESCENDING}},
        {"$limit": limit},
        {"$project": {"_id": 0}},
    ]
    return list(_audit_collection().aggregate(pipeline))


def get_lineage(execution_id: str) -> list[dict[str, Any]]:
    """Return chunk-level provenance rows for one agent answer."""

    return list(
        _lineage_collection()
        .find({"execution_id": execution_id}, {"_id": 0})
        .sort("citation_index", ASCENDING)
    )
