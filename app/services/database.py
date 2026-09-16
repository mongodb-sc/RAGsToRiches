"""Pooled PyMongo connection used by FastAPI, Streamlit, and seed scripts.

A single ``MongoClient`` is created per process. PyMongo multiplexes that
client across a connection pool, so request handlers should borrow a
database handle rather than constructing a new client on every call.

MongoDB documentation:
- PyMongo driver: https://www.mongodb.com/docs/languages/python/pymongo-driver/current/
- Connection pools: https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/
- Atlas connection strings: https://www.mongodb.com/docs/manual/reference/connection-string/
"""

from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, PyMongoError

from app.config import Settings, get_settings

_client: MongoClient[dict[str, Any]] | None = None


def get_client(settings: Settings | None = None) -> MongoClient[dict[str, Any]]:
    """Return the process-wide pooled MongoClient.

    Pool settings stay conservative for a demo cluster: enough sockets for
    concurrent Streamlit and FastAPI traffic without saturating a free-tier
    Atlas connection limit.
    """

    global _client
    if _client is not None:
        return _client

    resolved = settings or get_settings()
    _client = MongoClient(
        resolved.mongodb_uri,
        maxPoolSize=50,
        minPoolSize=2,
        maxIdleTimeMS=45_000,
        serverSelectionTimeoutMS=8_000,
        connectTimeoutMS=8_000,
        retryWrites=True,
        retryReads=True,
        appname="atlas-retail-banking-rag",
    )
    return _client


def get_database(settings: Settings | None = None) -> Database[dict[str, Any]]:
    """Return the retail banking database handle."""

    resolved = settings or get_settings()
    return get_client(resolved)[resolved.mongodb_db_name]


def get_collection(name: str, settings: Settings | None = None) -> Collection[dict[str, Any]]:
    """Return a named collection from the retail banking database."""

    return get_database(settings)[name]


def ping_atlas() -> dict[str, Any]:
    """Run ``hello`` against Atlas and return a compact health payload.

    Used by the FastAPI ``/health`` route and the Streamlit sidebar so
    operators can see whether the demo is talking to a live cluster.
    """

    settings = get_settings()
    try:
        hello = get_client(settings).admin.command("hello")
        return {
            "ok": True,
            "database": settings.mongodb_db_name,
            "cluster_time_present": "clusterTime" in hello or "$clusterTime" in hello,
            "hosts": hello.get("hosts", hello.get("me")),
        }
    except (ConnectionFailure, PyMongoError) as exc:
        return {"ok": False, "database": settings.mongodb_db_name, "error": str(exc)}


def close_client() -> None:
    """Close the pooled client. Called from FastAPI shutdown hooks."""

    global _client
    if _client is not None:
        _client.close()
        _client = None
