"""LangGraph banking agent with a custom MongoDB checkpointer.

The graph is a linear specialist pipeline:

    recall_memory -> vector_search -> graph_traversal -> final_answer

Each node imports the existing RAG and ``$graphLookup`` services rather
than reimplementing them. ``MongoDBSaver`` persists LangGraph checkpoints
into the ``checkpoints`` collection so a thread can be inspected, rewound,
or resumed.

MongoDB documentation:
- Transactions and durability: https://www.mongodb.com/docs/manual/core/transactions/
- LangGraph + Atlas: https://www.mongodb.com/docs/atlas/atlas-vector-search/ai-integrations/langchain/
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import uuid4

from bson.binary import Binary
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.graph import END, START, StateGraph
from pymongo import ASCENDING, DESCENDING

from app.config import Settings, get_settings
from app.services.agent_memory import (
    append_session_turn,
    fetch_session_turns,
    memory_brief,
    retrieve_long_term_memory,
)
from app.services.audit_lineage import (
    log_agent_step,
    new_execution_id,
    track_provenance,
)
from app.services.database import get_collection
from app.services.graph_service import get_customer_graph
from app.services.security import normalize_role
from app.services.vector_search import (
    generate_answer,
    hybrid_search,
    synthesize_prompt,
    vector_search,
)


def _now() -> datetime:
    """Return a timezone-aware UTC timestamp for checkpoint documents."""

    return datetime.now(timezone.utc)


def json_safe(value: Any) -> Any:
    """Convert nested values into BSON- and JSON-safe Python types."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return str(value)


class AgentState(TypedDict, total=False):
    """Shared state passed through every LangGraph node in one agent run."""

    question: str
    thread_id: str
    customer_id: str
    user_role: str
    execution_id: str
    product_type: str | None
    search_mode: str
    max_depth: int
    session_turns: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    graph: dict[str, Any]
    answer: str
    citations: list[dict[str, Any]]
    prompt: str
    step_log: list[dict[str, Any]]


class MongoDBSaver(BaseCheckpointSaver[int]):
    """Persist LangGraph checkpoints and pending writes in Atlas.

    Checkpoints are stored as serialized blobs plus a denormalized
    ``state_snapshot`` so the Streamlit inspector can render history
    without decoding LangGraph's internal serde format.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or get_settings()
        self._ensure_indexes()

    def _checkpoints(self):
        """Return the ``checkpoints`` collection."""

        return get_collection(self.settings.checkpoints_collection, self.settings)

    def _writes(self):
        """Return the ``checkpoint_writes`` collection."""

        return get_collection(self.settings.checkpoint_writes_collection, self.settings)

    def _ensure_indexes(self) -> None:
        """Create unique keys used for thread lookup and time-travel."""

        self._checkpoints().create_index(
            [
                ("thread_id", ASCENDING),
                ("checkpoint_ns", ASCENDING),
                ("checkpoint_id", ASCENDING),
            ],
            unique=True,
        )
        self._checkpoints().create_index(
            [("thread_id", ASCENDING), ("created_at", DESCENDING)]
        )
        self._writes().create_index(
            [
                ("thread_id", ASCENDING),
                ("checkpoint_ns", ASCENDING),
                ("checkpoint_id", ASCENDING),
                ("task_id", ASCENDING),
                ("idx", ASCENDING),
            ],
            unique=True,
        )

    def _encode(self, value: Any) -> tuple[str, Binary]:
        """Serialize a checkpoint or write with the LangGraph serde."""

        type_name, payload = self.serde.dumps_typed(value)
        return type_name, Binary(payload)

    def _decode(self, type_name: str, payload: Any) -> Any:
        """Deserialize a blob stored by ``_encode``."""

        return self.serde.loads_typed((type_name, bytes(payload)))

    def _row_to_tuple(self, document: dict[str, Any]) -> CheckpointTuple:
        """Rebuild a ``CheckpointTuple`` from one MongoDB checkpoint document."""

        checkpoint = self._decode(document["type"], document["checkpoint"])
        metadata = document.get("metadata") or {}
        parent_id = document.get("parent_checkpoint_id")
        writes = list(
            self._writes().find(
                {
                    "thread_id": document["thread_id"],
                    "checkpoint_ns": document["checkpoint_ns"],
                    "checkpoint_id": document["checkpoint_id"],
                }
            )
        )
        pending = [
            (
                row["task_id"],
                row["channel"],
                self._decode(row["type"], row["value"]),
            )
            for row in writes
        ]
        parent_config = (
            {
                "configurable": {
                    "thread_id": document["thread_id"],
                    "checkpoint_ns": document["checkpoint_ns"],
                    "checkpoint_id": parent_id,
                }
            }
            if parent_id
            else None
        )
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": document["thread_id"],
                    "checkpoint_ns": document["checkpoint_ns"],
                    "checkpoint_id": document["checkpoint_id"],
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending,
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Load the latest checkpoint for a thread, or a specific checkpoint id."""

        configurable = config.get("configurable") or {}
        thread_id = configurable.get("thread_id")
        if not thread_id:
            return None
        query: dict[str, Any] = {
            "thread_id": thread_id,
            "checkpoint_ns": configurable.get("checkpoint_ns", ""),
        }
        checkpoint_id = get_checkpoint_id(config)
        if checkpoint_id:
            query["checkpoint_id"] = checkpoint_id
            document = self._checkpoints().find_one(query)
        else:
            document = self._checkpoints().find_one(
                query, sort=[("checkpoint_id", DESCENDING)]
            )
        if not document:
            return None
        return self._row_to_tuple(document)

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        """Yield checkpoints for a thread, newest first."""

        query: dict[str, Any] = {}
        if config:
            configurable = config.get("configurable") or {}
            if configurable.get("thread_id"):
                query["thread_id"] = configurable["thread_id"]
            if "checkpoint_ns" in configurable:
                query["checkpoint_ns"] = configurable.get("checkpoint_ns", "")
        if before and get_checkpoint_id(before):
            query["checkpoint_id"] = {"$lt": get_checkpoint_id(before)}
        if filter:
            for key, value in filter.items():
                query[f"metadata.{key}"] = value
        cursor = self._checkpoints().find(query).sort("checkpoint_id", DESCENDING)
        if limit:
            cursor = cursor.limit(limit)
        for document in cursor:
            yield self._row_to_tuple(document)

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Insert or replace one graph snapshot and return the new config."""

        del new_versions
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        type_name, blob = self._encode(checkpoint)
        merged_metadata = get_checkpoint_metadata(config, metadata)
        document = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint["id"],
            "parent_checkpoint_id": configurable.get("checkpoint_id"),
            "type": type_name,
            "checkpoint": blob,
            "metadata": json_safe(merged_metadata),
            "state_snapshot": json_safe(checkpoint.get("channel_values") or {}),
            "created_at": _now(),
        }
        self._checkpoints().replace_one(
            {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            },
            document,
            upsert=True,
        )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store intermediate channel writes attached to a checkpoint."""

        configurable = config["configurable"]
        for index, (channel, value) in enumerate(writes):
            write_index = WRITES_IDX_MAP.get(channel, index)
            type_name, blob = self._encode(value)
            self._writes().replace_one(
                {
                    "thread_id": configurable["thread_id"],
                    "checkpoint_ns": configurable.get("checkpoint_ns", ""),
                    "checkpoint_id": configurable["checkpoint_id"],
                    "task_id": task_id,
                    "idx": write_index,
                },
                {
                    "thread_id": configurable["thread_id"],
                    "checkpoint_ns": configurable.get("checkpoint_ns", ""),
                    "checkpoint_id": configurable["checkpoint_id"],
                    "task_id": task_id,
                    "task_path": task_path,
                    "idx": write_index,
                    "channel": channel,
                    "type": type_name,
                    "value": blob,
                    "created_at": _now(),
                },
                upsert=True,
            )

    def delete_thread(self, thread_id: str) -> None:
        """Remove every checkpoint and write for one conversation thread."""

        self._checkpoints().delete_many({"thread_id": thread_id})
        self._writes().delete_many({"thread_id": thread_id})

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Async wrapper around ``get_tuple`` for LangGraph's async runtime."""

        return self.get_tuple(config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Async wrapper around ``list``."""

        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Async wrapper around ``put``."""

        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Async wrapper around ``put_writes``."""

        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        """Async wrapper around ``delete_thread``."""

        self.delete_thread(thread_id)


def list_checkpoint_history(thread_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return UI-friendly checkpoint snapshots for one thread, newest first."""

    settings = get_settings()
    cursor = (
        get_collection(settings.checkpoints_collection, settings)
        .find(
            {"thread_id": thread_id},
            {
                "_id": 0,
                "thread_id": 1,
                "checkpoint_id": 1,
                "parent_checkpoint_id": 1,
                "metadata": 1,
                "state_snapshot": 1,
                "created_at": 1,
            },
        )
        .sort("created_at", DESCENDING)
        .limit(limit)
    )
    rows = []
    for document in cursor:
        snapshot = document.get("state_snapshot") or {}
        rows.append(
            {
                **document,
                "created_at": json_safe(document.get("created_at")),
                "step_log": snapshot.get("step_log") or [],
                "answer": snapshot.get("answer"),
                "question": snapshot.get("question"),
                "execution_id": snapshot.get("execution_id"),
            }
        )
    return rows


def get_checkpoint_snapshot(thread_id: str, checkpoint_id: str) -> dict[str, Any] | None:
    """Load one denormalized state snapshot for rewind / inspect."""

    settings = get_settings()
    document = get_collection(settings.checkpoints_collection, settings).find_one(
        {"thread_id": thread_id, "checkpoint_id": checkpoint_id},
        {"_id": 0, "checkpoint": 0},
    )
    if not document:
        return None
    document["created_at"] = json_safe(document.get("created_at"))
    return document


def rewind_to_checkpoint(thread_id: str, checkpoint_id: str) -> dict[str, Any]:
    """Return the snapshot at ``checkpoint_id`` so the UI can time-travel.

    The next ``run_agent`` call on the same ``thread_id`` can pass
    ``checkpoint_id`` to resume LangGraph from that exact node state.
    """

    snapshot = get_checkpoint_snapshot(thread_id, checkpoint_id)
    if snapshot is None:
        raise ValueError(f"No checkpoint {checkpoint_id} for thread {thread_id}")
    return {
        "thread_id": thread_id,
        "checkpoint_id": checkpoint_id,
        "resume_config": {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        },
        "state": snapshot.get("state_snapshot") or {},
        "metadata": snapshot.get("metadata") or {},
        "created_at": snapshot.get("created_at"),
    }


def _append_step(state: AgentState, entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Copy the existing step log and append one node record."""

    history = list(state.get("step_log") or [])
    history.append(entry)
    return history


def _timed(name: str, tool: str, thought: str, state: AgentState, work):
    """Run a node body, time it, and write an audit row."""

    started = time.perf_counter()
    tool_input, tool_output, updates = work()
    latency_ms = (time.perf_counter() - started) * 1000
    log_agent_step(
        execution_id=state["execution_id"],
        thread_id=state["thread_id"],
        user_role=state["user_role"],
        customer_id=state.get("customer_id"),
        step_name=name,
        tool_called=tool,
        tool_input=json_safe(tool_input),
        tool_output=json_safe(tool_output),
        reasoning_thought=thought,
        execution_latency_ms=latency_ms,
    )
    updates["step_log"] = _append_step(
        state,
        {
            "step_name": name,
            "tool_called": tool,
            "execution_latency_ms": round(latency_ms, 2),
            "reasoning_thought": thought,
        },
    )
    return updates


def recall_memory_node(state: AgentState) -> dict[str, Any]:
    """Load short-term turns and long-term vector memories for the customer."""

    def work() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        turns = fetch_session_turns(
            state["thread_id"], user_role=state["user_role"]
        )
        memories = retrieve_long_term_memory(
            state["customer_id"],
            state["question"],
            user_role=state["user_role"],
        )
        tool_input = {
            "thread_id": state["thread_id"],
            "customer_id": state["customer_id"],
            "query": state["question"],
        }
        tool_output = {
            "session_turn_count": len(turns),
            "memory_ids": [item.get("memory_id") for item in memories],
        }
        return tool_input, tool_output, {"session_turns": turns, "memories": memories}

    return _timed(
        "recall_memory",
        "retrieve_long_term_memory+fetch_session_turns",
        "Recall this customer's durable preferences and the active thread buffer.",
        state,
        work,
    )


def vector_search_node(state: AgentState) -> dict[str, Any]:
    """Delegate retrieval to the existing hybrid / vector search services."""

    def work() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        kwargs = {
            "product_type": state.get("product_type"),
            "user_role": state["user_role"],
        }
        if state.get("search_mode") == "vector":
            chunks = vector_search(state["question"], **kwargs)
        else:
            chunks = hybrid_search(state["question"], **kwargs)
        tool_input = {
            "question": state["question"],
            "search_mode": state.get("search_mode") or "hybrid",
            "product_type": state.get("product_type"),
        }
        tool_output = {
            "chunk_ids": [chunk.get("doc_id") for chunk in chunks],
            "count": len(chunks),
        }
        return tool_input, tool_output, {"chunks": chunks}

    return _timed(
        "vector_search",
        "hybrid_search" if state.get("search_mode") != "vector" else "vector_search",
        "Retrieve authorized policy and transcript passages from Atlas Vector Search.",
        state,
        work,
    )


def graph_traversal_node(state: AgentState) -> dict[str, Any]:
    """Delegate household expansion to the existing ``$graphLookup`` service."""

    def work() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        payload = get_customer_graph(
            state["customer_id"],
            max_depth=int(state.get("max_depth") or 3),
            user_role=state["user_role"],
        )
        stats = payload.get("stats") or {}
        compact = {
            "root": payload.get("root"),
            "stats": stats,
            "node_ids": [node.get("id") for node in (payload.get("nodes") or [])][:20],
        }
        tool_input = {
            "customer_id": state["customer_id"],
            "max_depth": state.get("max_depth") or 3,
        }
        return tool_input, compact, {"graph": compact}

    return _timed(
        "graph_traversal",
        "get_customer_graph",
        "Walk the household and joint-account network with $graphLookup.",
        state,
        work,
    )


def final_answer_node(state: AgentState) -> dict[str, Any]:
    """Ground the LLM on recalled memory plus retrieved Atlas chunks."""

    def work() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        chunks = list(state.get("chunks") or [])
        memory_context = memory_brief(state.get("memories") or [])
        graph_stats = (state.get("graph") or {}).get("stats") or {}
        question = (
            f"{state['question']}\n\n"
            f"Known customer memories:\n{memory_context}\n\n"
            f"Household graph summary: {graph_stats}"
        )
        answer = generate_answer(question, chunks, state["user_role"])
        prompt = synthesize_prompt(question, chunks, state["user_role"])
        citations = [
            {
                "index": index,
                "doc_id": chunk.get("doc_id"),
                "title": chunk.get("title"),
                "score": chunk.get("vector_score") or chunk.get("score"),
                "source": chunk.get("source"),
                "clearance_level": chunk.get("clearance_level"),
            }
            for index, chunk in enumerate(chunks, start=1)
        ]
        append_session_turn(
            state["thread_id"],
            "user",
            state["question"],
            customer_id=state.get("customer_id"),
            user_role=state["user_role"],
            execution_id=state["execution_id"],
        )
        append_session_turn(
            state["thread_id"],
            "assistant",
            answer,
            customer_id=state.get("customer_id"),
            user_role=state["user_role"],
            execution_id=state["execution_id"],
        )
        lineage = track_provenance(
            execution_id=state["execution_id"],
            thread_id=state["thread_id"],
            answer=answer,
            chunks=chunks,
            user_role=state["user_role"],
            customer_id=state.get("customer_id"),
            question=state["question"],
        )
        tool_input = {"question": state["question"], "chunk_count": len(chunks)}
        tool_output = {
            "answer_preview": answer[:280],
            "citation_count": len(citations),
            "lineage_chunks": lineage.get("chunk_count"),
        }
        return (
            tool_input,
            tool_output,
            {"answer": answer, "citations": citations, "prompt": prompt},
        )

    return _timed(
        "final_answer",
        "generate_answer+track_provenance",
        "Synthesize a cited answer and persist session turns plus chunk lineage.",
        state,
        work,
    )


def build_agent_graph(checkpointer: MongoDBSaver | None = None):
    """Compile the four-node banking agent with the MongoDB checkpointer."""

    saver = checkpointer or MongoDBSaver()
    builder = StateGraph(AgentState)
    builder.add_node("recall_memory", recall_memory_node)
    builder.add_node("vector_search", vector_search_node)
    builder.add_node("graph_traversal", graph_traversal_node)
    builder.add_node("final_answer", final_answer_node)
    builder.add_edge(START, "recall_memory")
    builder.add_edge("recall_memory", "vector_search")
    builder.add_edge("vector_search", "graph_traversal")
    builder.add_edge("graph_traversal", "final_answer")
    builder.add_edge("final_answer", END)
    return builder.compile(checkpointer=saver)


def run_agent(
    question: str,
    *,
    thread_id: str | None = None,
    customer_id: str = "CUST-0001",
    user_role: str = "tier1_support",
    product_type: str | None = None,
    search_mode: str = "hybrid",
    max_depth: int = 3,
    checkpoint_id: str | None = None,
) -> dict[str, Any]:
    """Execute the LangGraph agent and return the final state plus ids."""

    resolved_thread = thread_id or f"THR-{uuid4().hex[:12]}"
    execution_id = new_execution_id()
    graph = build_agent_graph()
    configurable: dict[str, Any] = {"thread_id": resolved_thread}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    result = graph.invoke(
        {
            "question": question,
            "thread_id": resolved_thread,
            "customer_id": customer_id,
            "user_role": normalize_role(user_role),
            "execution_id": execution_id,
            "product_type": product_type,
            "search_mode": search_mode,
            "max_depth": max_depth,
            "step_log": [],
        },
        {"configurable": configurable},
    )
    latest = list_checkpoint_history(resolved_thread, limit=1)
    return {
        "thread_id": resolved_thread,
        "execution_id": execution_id,
        "checkpoint_id": latest[0]["checkpoint_id"] if latest else None,
        "answer": result.get("answer"),
        "citations": result.get("citations") or [],
        "memories": result.get("memories") or [],
        "session_turns": result.get("session_turns") or [],
        "chunks": result.get("chunks") or [],
        "graph": result.get("graph") or {},
        "step_log": result.get("step_log") or [],
        "prompt": result.get("prompt"),
        "role": normalize_role(user_role),
        "customer_id": customer_id,
        "question": question,
    }
