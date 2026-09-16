"""FastAPI entrypoint for the Atlas retail-banking RAG platform.

The API exposes the same services used by the Streamlit dashboard so a
mobile or contact-center client can call chat, graph lookup, and
governance filtering without going through the UI.

MongoDB documentation:
- Atlas as an operational + AI data platform: https://www.mongodb.com/docs/atlas/
- Vector Search: https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-overview/
- ``$graphLookup``: https://www.mongodb.com/docs/manual/reference/operator/aggregation/graphLookup/

Cursor prompts that produced this codebase (see the docs canvas for full text):
1. Build FastAPI + Streamlit Atlas RAG/data platform for retail banking.
2. Add Screenpipe MCP so the agent can record the browser walkthrough.
3. Document source, MongoDB links, use cases, requirements, and walkthroughs.
4. Add those Cursor prompts to the documentation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.database import close_client, ping_atlas
from app.services.agent_memory import fetch_session_turns, retrieve_long_term_memory
from app.services.agent_workflow import (
    list_checkpoint_history,
    rewind_to_checkpoint,
    run_agent,
)
from app.services.audit_lineage import get_lineage, list_audit_logs, list_recent_executions
from app.services.graph_service import get_customer_graph, list_customers
from app.services.security import filter_context_by_role, role_policy_summary
from app.services.vector_search import (
    build_vector_search_pipeline,
    embed_text,
    rag_chat,
    synthesize_prompt,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Open the pooled Mongo client on startup and close it on shutdown."""

    ping_atlas()
    yield
    close_client()


app = FastAPI(
    title="Atlas National Bank RAG Platform",
    description=(
        "MongoDB Atlas as a retail-banking RAG and data platform: "
        "Vector Search, hybrid search, $graphLookup household networks, "
        "and role-based PII redaction."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    """Question submitted to the banking RAG assistant."""

    question: str = Field(min_length=3, max_length=4_000)
    user_role: Literal["tier1_support", "compliance_manager"] = "tier1_support"
    product_type: str | None = None
    search_mode: Literal["hybrid", "vector"] = "hybrid"
    limit: int = Field(default=6, ge=1, le=20)


class GovernanceRequest(BaseModel):
    """Chunks to filter through the role-based redaction engine."""

    user_role: Literal["tier1_support", "compliance_manager"]
    retrieved_chunks: list[dict[str, Any]]


class PromptRequest(BaseModel):
    """Optional helper that only builds the grounded LLM prompt."""

    question: str
    user_role: Literal["tier1_support", "compliance_manager"] = "tier1_support"
    chunks: list[dict[str, Any]]


class AgentRunRequest(BaseModel):
    """Input for the LangGraph memory-aware banking agent."""

    question: str = Field(min_length=3, max_length=4_000)
    thread_id: str | None = None
    customer_id: str = "CUST-0001"
    user_role: Literal["tier1_support", "compliance_manager"] = "tier1_support"
    product_type: str | None = None
    search_mode: Literal["hybrid", "vector"] = "hybrid"
    max_depth: int = Field(default=3, ge=1, le=5)
    checkpoint_id: str | None = None


class RewindRequest(BaseModel):
    """Select a prior LangGraph checkpoint for time-travel inspection."""

    thread_id: str
    checkpoint_id: str


@app.get("/health")
def health() -> dict[str, Any]:
    """Return Atlas connectivity and database name."""

    return ping_atlas()


@app.get("/api/customers")
def customers(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    """List seeded customers for graph and chat pickers."""

    return {"customers": list_customers(limit=limit)}


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    """Retrieve Atlas context and generate a cited answer."""

    try:
        return rag_chat(
            request.question,
            user_role=request.user_role,
            product_type=request.product_type,
            search_mode=request.search_mode,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/graph/{customer_id}")
def customer_graph(
    customer_id: str,
    max_depth: int = Query(default=3, ge=1, le=5),
    user_role: Literal["tier1_support", "compliance_manager"] = "compliance_manager",
) -> dict[str, Any]:
    """Return a PyVis-ready household and account network."""

    payload = get_customer_graph(
        customer_id,
        max_depth=max_depth,
        user_role=user_role,
    )
    if payload.get("root") is None:
        raise HTTPException(status_code=404, detail=payload.get("message"))
    return payload


@app.post("/api/governance/filter")
def governance_filter(request: GovernanceRequest) -> dict[str, Any]:
    """Apply live role-based context filtering and PII redaction."""

    try:
        filtered = filter_context_by_role(request.user_role, request.retrieved_chunks)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "role": request.user_role,
        "policy": role_policy_summary(request.user_role),
        "input_count": len(request.retrieved_chunks),
        "output_count": len(filtered),
        "chunks": filtered,
    }


@app.post("/api/prompt")
def prompt_preview(request: PromptRequest) -> dict[str, Any]:
    """Show the exact prompt that would be sent to the chat model."""

    return {
        "prompt": synthesize_prompt(request.question, request.chunks, request.user_role)
    }


@app.get("/api/vector-pipeline")
def vector_pipeline_preview(
    question: str = Query(default="What is the outgoing domestic wire fee?"),
    product_type: str | None = None,
) -> dict[str, Any]:
    """Return the raw ``$vectorSearch`` pipeline for teaching and debugging."""

    settings = get_settings()
    query_vector = embed_text(question, settings)
    filters = {"product_type": {"$eq": product_type}} if product_type else None
    pipeline = build_vector_search_pipeline(query_vector, filters=filters)
    sanitized = []
    for stage in pipeline:
        if "$vectorSearch" in stage:
            copied = dict(stage)
            search = dict(copied["$vectorSearch"])
            search["queryVector"] = f"<{len(query_vector)}-dimension embedding omitted>"
            copied["$vectorSearch"] = search
            sanitized.append(copied)
        else:
            sanitized.append(stage)
    return {"pipeline": sanitized, "index": settings.vector_index_name}


@app.post("/api/agent/run")
def agent_run(request: AgentRunRequest) -> dict[str, Any]:
    """Run the LangGraph agent with MongoDB memory, checkpoints, and audit."""

    try:
        return run_agent(
            request.question,
            thread_id=request.thread_id,
            customer_id=request.customer_id,
            user_role=request.user_role,
            product_type=request.product_type,
            search_mode=request.search_mode,
            max_depth=request.max_depth,
            checkpoint_id=request.checkpoint_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/agent/session/{thread_id}")
def agent_session(thread_id: str, user_role: str = "tier1_support") -> dict[str, Any]:
    """Return the short-term conversation buffer for a thread."""

    return {"thread_id": thread_id, "turns": fetch_session_turns(thread_id, user_role=user_role)}


@app.get("/api/agent/memory/{customer_id}")
def agent_long_term_memory(
    customer_id: str,
    query: str = Query(default="customer preferences and recent applications"),
    user_role: str = "compliance_manager",
) -> dict[str, Any]:
    """Recall long-term vector memories for one customer."""

    return {
        "customer_id": customer_id,
        "memories": retrieve_long_term_memory(customer_id, query, user_role=user_role),
    }


@app.get("/api/agent/checkpoints/{thread_id}")
def agent_checkpoints(thread_id: str, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    """List persisted LangGraph checkpoints for inspector and rewind."""

    return {"thread_id": thread_id, "checkpoints": list_checkpoint_history(thread_id, limit=limit)}


@app.post("/api/agent/rewind")
def agent_rewind(request: RewindRequest) -> dict[str, Any]:
    """Return a prior workflow snapshot so the client can time-travel."""

    try:
        return rewind_to_checkpoint(request.thread_id, request.checkpoint_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/agent/audit")
def agent_audit(
    execution_id: str | None = None,
    thread_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Return audit rows and recent execution summaries."""

    return {
        "recent": list_recent_executions(limit=min(limit, 50)),
        "logs": list_audit_logs(
            execution_id=execution_id, thread_id=thread_id, limit=limit
        ),
    }


@app.get("/api/agent/lineage/{execution_id}")
def agent_lineage(execution_id: str) -> dict[str, Any]:
    """Return chunk-level provenance for one generated answer."""

    return {"execution_id": execution_id, "chunks": get_lineage(execution_id)}
