"""Household and account network traversal with ``$graphLookup``.

Every customer, household, account, and recent joint transaction is stored
as a node in ``graph_nodes`` with a ``connections`` array of neighboring
``node_id`` values. ``$graphLookup`` walks those edges so a single
aggregation can return the customer's multi-tier financial graph.

MongoDB documentation:
- ``$graphLookup``: https://www.mongodb.com/docs/manual/reference/operator/aggregation/graphLookup/
- Aggregation pipeline: https://www.mongodb.com/docs/manual/core/aggregation-pipeline/
- ``$lookup`` (joint transactions): https://www.mongodb.com/docs/manual/reference/operator/aggregation/lookup/
- Graph data in MongoDB: https://www.mongodb.com/docs/manual/applications/data-models-tree-structures/
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.services.database import get_collection
from app.services.security import filter_context_by_role, normalize_role

NODE_COLORS = {
    "customer": "#00ED64",
    "household": "#FFC010",
    "account": "#016BF8",
    "transaction": "#DB3030",
}

NODE_SHAPES = {
    "customer": "dot",
    "household": "hexagon",
    "account": "box",
    "transaction": "diamond",
}


def build_graph_lookup_pipeline(
    customer_id: str,
    *,
    max_depth: int = 3,
) -> list[dict[str, Any]]:
    """Return the aggregation that expands one customer's financial graph.

    ``startWith`` seeds the walk from the customer's own ``connections``.
    ``connectFromField`` / ``connectToField`` then hop across household
    members, joint accounts, and joint transactions up to ``max_depth``.

    Spec: https://www.mongodb.com/docs/manual/reference/operator/aggregation/graphLookup/
    """

    settings = get_settings()
    return [
        {"$match": {"node_id": customer_id, "node_type": "customer"}},
        {
            "$graphLookup": {
                "from": settings.graph_collection,
                "startWith": "$connections",
                "connectFromField": "connections",
                "connectToField": "node_id",
                "as": "network",
                "maxDepth": max_depth,
                "depthField": "hop_depth",
            }
        },
        {
            "$lookup": {
                "from": settings.transactions_collection,
                "let": {"root_customer": "$node_id", "network_ids": "$network.node_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$is_joint", True]},
                                    {
                                        "$or": [
                                            {"$in": ["$account_id", "$$network_ids"]},
                                            {"$in": ["$$root_customer", "$customer_ids"]},
                                        ]
                                    },
                                ]
                            }
                        }
                    },
                    {"$sort": {"timestamp": -1}},
                    {"$limit": 8},
                ],
                "as": "recent_joint_transactions",
            }
        },
        {
            "$project": {
                "_id": 0,
                "node_id": 1,
                "node_type": 1,
                "label": 1,
                "connections": 1,
                "metadata": 1,
                "network": 1,
                "recent_joint_transactions": 1,
            }
        },
    ]


def _as_node(document: dict[str, Any], depth: int) -> dict[str, Any]:
    """Normalize a graph_nodes document into a PyVis-ready node."""

    node_type = str(document.get("node_type") or "customer")
    metadata = document.get("metadata") or {}
    return {
        "id": document.get("node_id"),
        "label": document.get("label") or document.get("node_id"),
        "type": node_type,
        "depth": depth,
        "color": NODE_COLORS.get(node_type, "#E8EDEB"),
        "shape": NODE_SHAPES.get(node_type, "dot"),
        "metadata": metadata,
        "title": _tooltip(document, depth),
    }


def _tooltip(document: dict[str, Any], depth: int) -> str:
    """Build the hover caption shown in the PyVis canvas."""

    metadata = document.get("metadata") or {}
    details = [f"{document.get('node_type')}: {document.get('label')}", f"depth: {depth}"]
    for key in ("account_type", "product_type", "status", "household_id", "relationship"):
        if metadata.get(key):
            details.append(f"{key}: {metadata[key]}")
    if "balance" in metadata:
        details.append(f"balance: {metadata['balance']}")
    if metadata.get("ssn"):
        details.append(f"ssn: {metadata['ssn']}")
    return " | ".join(details)


def _transaction_node(transaction: dict[str, Any]) -> dict[str, Any]:
    """Wrap a joint transaction as a first-class graph node."""

    amount = transaction.get("amount")
    amount_label = f"${amount:,.2f}" if isinstance(amount, (int, float)) else str(amount)
    label = f"{transaction.get('type', 'txn')} {amount_label}"
    node_id = str(transaction.get("transaction_id"))
    return {
        "id": node_id,
        "label": label,
        "type": "transaction",
        "depth": 3,
        "color": NODE_COLORS["transaction"],
        "shape": NODE_SHAPES["transaction"],
        "metadata": {
            "amount": amount,
            "type": transaction.get("type"),
            "account_id": transaction.get("account_id"),
            "related_account_id": transaction.get("related_account_id"),
            "timestamp": str(transaction.get("timestamp")),
            "is_joint": True,
        },
        "title": f"joint {transaction.get('type')} {amount_label}",
        "connections": [
            item
            for item in [
                transaction.get("account_id"),
                transaction.get("related_account_id"),
                *(transaction.get("customer_ids") or []),
            ]
            if item
        ],
    }


def to_pyvis_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten a ``$graphLookup`` result into nodes and edges for PyVis."""

    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str]] = set()

    root = _as_node(raw, depth=0)
    nodes_by_id[str(root["id"])] = root

    for neighbor in raw.get("network") or []:
        node = _as_node(neighbor, depth=int(neighbor.get("hop_depth", 0)) + 1)
        nodes_by_id[str(node["id"])] = node

    for transaction in raw.get("recent_joint_transactions") or []:
        node = _transaction_node(transaction)
        nodes_by_id[str(node["id"])] = node

    def add_edge(source: str, target: str, relation: str) -> None:
        if not source or not target or source == target:
            return
        if source not in nodes_by_id or target not in nodes_by_id:
            return
        key = (source, target)
        reverse = (target, source)
        if key in seen_edges or reverse in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"from": source, "to": target, "relation": relation})

    all_docs = [raw, *(raw.get("network") or [])]
    for document in all_docs:
        source_id = str(document.get("node_id"))
        source_type = str(document.get("node_type") or "")
        for target_id in document.get("connections") or []:
            target = nodes_by_id.get(str(target_id))
            if not target:
                continue
            target_type = str(target.get("type") or "")
            if {source_type, target_type} == {"customer", "household"}:
                relation = "household_member"
            elif {source_type, target_type} == {"customer", "account"}:
                relation = "owns"
            elif {source_type, target_type} == {"account", "household"}:
                relation = "household_account"
            elif source_type == "customer" and target_type == "customer":
                relation = "related"
            else:
                relation = "linked"
            add_edge(source_id, str(target_id), relation)

    for transaction in raw.get("recent_joint_transactions") or []:
        txn_id = str(transaction.get("transaction_id"))
        for account_id in (transaction.get("account_id"), transaction.get("related_account_id")):
            if account_id:
                add_edge(str(account_id), txn_id, "joint_transaction")
        for customer_id in transaction.get("customer_ids") or []:
            add_edge(str(customer_id), txn_id, "party")

    return {
        "root": root,
        "nodes": list(nodes_by_id.values()),
        "edges": edges,
        "stats": {
            "node_count": len(nodes_by_id),
            "edge_count": len(edges),
            "customers": sum(1 for node in nodes_by_id.values() if node["type"] == "customer"),
            "accounts": sum(1 for node in nodes_by_id.values() if node["type"] == "account"),
            "households": sum(1 for node in nodes_by_id.values() if node["type"] == "household"),
            "transactions": sum(1 for node in nodes_by_id.values() if node["type"] == "transaction"),
        },
    }


def apply_graph_governance(payload: dict[str, Any], user_role: str) -> dict[str, Any]:
    """Redact node metadata for Tier 1 agents using the shared security rules."""

    role = normalize_role(user_role)
    chunked = [
        {
            "source": "account_metadata" if node["type"] in {"account", "transaction"} else "transcript",
            "clearance_level": "restricted" if node["type"] in {"customer", "account", "transaction"} else "public",
            "content": node.get("title") or "",
            "metadata": node.get("metadata") or {},
            "node_id": node.get("id"),
        }
        for node in payload.get("nodes") or []
    ]
    if role == "compliance_manager":
        return payload

    filtered = {item["node_id"]: item for item in filter_context_by_role(role, chunked)}
    redacted_nodes = []
    for node in payload.get("nodes") or []:
        updated = dict(node)
        governed = filtered.get(node["id"])
        if governed:
            updated["metadata"] = governed.get("metadata") or {}
            updated["title"] = governed.get("content") or updated.get("title")
        elif node["type"] in {"customer", "account", "transaction"}:
            metadata = dict(updated.get("metadata") or {})
            for key in ("ssn", "balance", "account_number", "date_of_birth"):
                if key in metadata:
                    metadata[key] = "[REDACTED]"
            updated["metadata"] = metadata
            updated["title"] = f"{updated['type']}: {updated['label']} | PII redacted"
        redacted_nodes.append(updated)
    return {**payload, "nodes": redacted_nodes, "role": role}


def get_customer_graph(
    customer_id: str,
    *,
    max_depth: int = 3,
    user_role: str = "compliance_manager",
) -> dict[str, Any]:
    """Execute ``$graphLookup`` and return a PyVis-ready JSON document."""

    settings = get_settings()
    collection = get_collection(settings.graph_collection, settings)
    pipeline = build_graph_lookup_pipeline(customer_id, max_depth=max_depth)
    results = list(collection.aggregate(pipeline))
    if not results:
        return {
            "root": None,
            "nodes": [],
            "edges": [],
            "stats": {
                "node_count": 0,
                "edge_count": 0,
                "customers": 0,
                "accounts": 0,
                "households": 0,
                "transactions": 0,
            },
            "pipeline": pipeline,
            "message": f"No graph node found for {customer_id}",
        }

    payload = to_pyvis_payload(results[0])
    payload["pipeline"] = pipeline
    return apply_graph_governance(payload, user_role)


def list_customers(limit: int = 50) -> list[dict[str, Any]]:
    """Return a compact customer roster for the Streamlit selector."""

    settings = get_settings()
    collection = get_collection(settings.customers_collection, settings)
    cursor = collection.find(
        {},
        {
            "_id": 0,
            "customer_id": 1,
            "first_name": 1,
            "last_name": 1,
            "household_id": 1,
            "account_ids": 1,
        },
    ).sort("customer_id", 1).limit(limit)
    return list(cursor)


def render_pyvis_html(payload: dict[str, Any]) -> str:
    """Create an interactive PyVis HTML string from a graph payload."""

    from pyvis.network import Network

    network = Network(
        height="640px",
        width="100%",
        bgcolor="#001E2B",
        font_color="#E8EDEB",
        directed=False,
    )
    network.barnes_hut(gravity=-18000, spring_length=140, spring_strength=0.02)
    network.set_options(
        """
        {
          "nodes": { "font": { "size": 14, "face": "Helvetica Neue" }, "borderWidth": 2 },
          "edges": { "color": { "color": "#5C6C75" }, "smooth": { "type": "continuous" } },
          "interaction": { "hover": true, "tooltipDelay": 120 },
          "physics": { "stabilization": { "iterations": 80 } }
        }
        """
    )

    for node in payload.get("nodes") or []:
        network.add_node(
            node["id"],
            label=str(node.get("label") or node["id"]),
            color=node.get("color"),
            shape=node.get("shape", "dot"),
            title=node.get("title") or "",
            size=22 if node.get("type") == "customer" else 16,
        )
    for edge in payload.get("edges") or []:
        network.add_edge(edge["from"], edge["to"], title=edge.get("relation", "linked"))

    return network.generate_html()
