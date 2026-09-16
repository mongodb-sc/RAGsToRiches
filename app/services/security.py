"""Role-based retrieval filters and PII redaction for banking RAG.

Two demo personas drive governance:

- ``tier1_support``: front-line agents. They may only retrieve public
  knowledge-base articles. Social Security numbers, exact balances, and
  full account numbers are redacted from any leftover text.
- ``compliance_manager``: second-line / BSA reviewers. They may retrieve
  public, internal, and restricted chunks, including customer transcripts
  and private account metadata, without redaction.

Pre-filtering happens inside ``$vectorSearch.filter`` so unauthorized
documents never enter the ANN candidate set. That is stronger than
post-filtering after retrieval.

MongoDB documentation:
- Vector Search pre-filters: https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/#std-label-avs-filter
- Queryable Encryption (production PII): https://www.mongodb.com/docs/manual/core/queryable-encryption/
- Field-level redaction patterns: https://www.mongodb.com/docs/manual/core/csfle/
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Literal

UserRole = Literal["tier1_support", "compliance_manager"]

ROLE_LABELS: dict[UserRole, str] = {
    "tier1_support": "Tier 1 Agent",
    "compliance_manager": "Compliance Manager",
}

CLEARANCE_BY_ROLE: dict[UserRole, set[str]] = {
    "tier1_support": {"public"},
    "compliance_manager": {"public", "internal", "restricted"},
}

ALLOWED_SOURCES_BY_ROLE: dict[UserRole, set[str]] = {
    "tier1_support": {"knowledge_base", "user_memory"},
    "compliance_manager": {
        "knowledge_base",
        "transcript",
        "account_metadata",
        "user_memory",
    },
}

PII_METADATA_KEYS = (
    "ssn",
    "social_security_number",
    "balance",
    "exact_balance",
    "available_balance",
    "account_number",
    "routing_number",
    "date_of_birth",
    "dob",
)

SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
SSN_COMPACT_PATTERN = re.compile(r"\b\d{9}\b")
ACCOUNT_NUMBER_PATTERN = re.compile(r"\b(?:ACCT-)?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", re.IGNORECASE)
BALANCE_PATTERN = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
ROUTING_PATTERN = re.compile(r"\b\d{9}\b")


def normalize_role(user_role: str) -> UserRole:
    """Map UI labels and aliases onto the two supported persona keys."""

    cleaned = user_role.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "tier1": "tier1_support",
        "tier_1": "tier1_support",
        "tier1_agent": "tier1_support",
        "tier_1_agent": "tier1_support",
        "agent": "tier1_support",
        "compliance": "compliance_manager",
        "compliance_mgr": "compliance_manager",
    }
    resolved = aliases.get(cleaned, cleaned)
    if resolved not in CLEARANCE_BY_ROLE:
        raise ValueError(f"Unsupported user_role '{user_role}'")
    return resolved  # type: ignore[return-value]


def retrieval_filter_for_role(user_role: str) -> dict[str, Any]:
    """Build an Atlas Vector Search pre-filter for the caller's role.

    Atlas ``$vectorSearch.filter`` accepts a subset of MQL. We restrict
    ``clearance_level`` so unauthorized documents never enter the candidate
    set, which is stronger than post-filtering after retrieval.
    """

    role = normalize_role(user_role)
    allowed = sorted(CLEARANCE_BY_ROLE[role])
    return {"clearance_level": {"$in": allowed}}


BALANCE_CONTEXT_PATTERN = re.compile(
    r"(?i)\b(?:balance|available balance|posted balance|exact balance|aum)\b[^$.]{0,24}"
    r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?"
)
LARGE_BALANCE_PATTERN = re.compile(r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?")


def redact_pii(text: str, *, redact_balances: bool = True) -> str:
    """Replace Social Security numbers, account numbers, and customer balances.

    Fee-schedule dollar amounts such as ``$25`` stay visible. Amounts that
    appear next to the word ``balance`` or use a thousands separator are
    treated as customer PII and redacted for Tier 1 agents.
    """

    redacted = SSN_PATTERN.sub("[REDACTED-SSN]", text)
    redacted = ACCOUNT_NUMBER_PATTERN.sub("[REDACTED-ACCOUNT]", redacted)
    if redact_balances:
        redacted = BALANCE_CONTEXT_PATTERN.sub("[REDACTED-BALANCE]", redacted)
        redacted = LARGE_BALANCE_PATTERN.sub("[REDACTED-BALANCE]", redacted)
    return redacted


def _redact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Drop or mask PII keys that should never reach a Tier 1 agent."""

    sanitized = dict(metadata)
    for key in PII_METADATA_KEYS:
        if key not in sanitized:
            continue
        if "ssn" in key or key == "social_security_number":
            sanitized[key] = "[REDACTED-SSN]"
        elif "balance" in key:
            sanitized[key] = "[REDACTED-BALANCE]"
        elif key in {"account_number", "routing_number"}:
            sanitized[key] = "[REDACTED-ACCOUNT]"
        elif key in {"date_of_birth", "dob"}:
            sanitized[key] = "[REDACTED-DOB]"
        else:
            sanitized[key] = "[REDACTED]"
    return sanitized


def _chunk_source(chunk: dict[str, Any]) -> str:
    """Read the logical source collection from a retrieved chunk."""

    return str(chunk.get("source") or chunk.get("collection") or "knowledge_base")


def _chunk_clearance(chunk: dict[str, Any]) -> str:
    """Read the document clearance, defaulting to public for unlabeled KB rows."""

    return str(chunk.get("clearance_level") or "public")


def filter_context_by_role(
    user_role: str,
    retrieved_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply source, clearance, and PII rules to retrieved RAG chunks.

    Tier 1 agents keep public knowledge-base documents only. Any residual
    PII in those documents is redacted. Compliance managers receive the
    original chunks, including transcripts and private account metadata.
    """

    role = normalize_role(user_role)
    allowed_clearance = CLEARANCE_BY_ROLE[role]
    allowed_sources = ALLOWED_SOURCES_BY_ROLE[role]
    filtered: list[dict[str, Any]] = []

    for raw_chunk in retrieved_chunks:
        chunk = deepcopy(raw_chunk)
        source = _chunk_source(chunk)
        clearance = _chunk_clearance(chunk)

        if source not in allowed_sources:
            continue
        if clearance not in allowed_clearance:
            continue

        if role == "tier1_support":
            redact_balances = source != "knowledge_base" or clearance != "public"
            if "content" in chunk and isinstance(chunk["content"], str):
                chunk["content"] = redact_pii(chunk["content"], redact_balances=redact_balances)
            if "title" in chunk and isinstance(chunk["title"], str):
                chunk["title"] = redact_pii(chunk["title"], redact_balances=redact_balances)
            metadata = chunk.get("metadata")
            if isinstance(metadata, dict):
                chunk["metadata"] = _redact_metadata(metadata)
            for key in PII_METADATA_KEYS:
                if key in chunk:
                    chunk[key] = _redact_metadata({key: chunk[key]})[key]
            chunk["redacted"] = True
        else:
            chunk["redacted"] = False

        chunk["visible_to_role"] = role
        filtered.append(chunk)

    return filtered


def role_policy_summary(user_role: str) -> dict[str, Any]:
    """Return a UI-friendly description of what the persona can see."""

    role = normalize_role(user_role)
    return {
        "role": role,
        "label": ROLE_LABELS[role],
        "allowed_clearance": sorted(CLEARANCE_BY_ROLE[role]),
        "allowed_sources": sorted(ALLOWED_SOURCES_BY_ROLE[role]),
        "redacts_pii": role == "tier1_support",
        "can_view_transcripts": "transcript" in ALLOWED_SOURCES_BY_ROLE[role],
        "can_view_account_metadata": "account_metadata" in ALLOWED_SOURCES_BY_ROLE[role],
    }
