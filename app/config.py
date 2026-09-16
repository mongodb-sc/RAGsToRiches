"""Application settings for MongoDB Atlas and OpenAI.

Values can be overridden with environment variables or a local ``.env`` file.
The Atlas URI default matches the demo cluster requested for this project.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment.

    ``mongodb_uri`` is the Atlas connection string used by the pooled PyMongo
    client. ``openai_api_key`` is required for real embeddings and chat
    completions; the seed and search services fall back to a deterministic
    local embedding if the key is missing so the demo still runs.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    mongodb_uri: str = Field(
        default="mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/",
        alias="MONGODB_URI",
    )
    mongodb_db_name: str = Field(default="retail_banking", alias="MONGODB_DB_NAME")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="OPENAI_EMBEDDING_MODEL",
    )
    openai_chat_model: str = Field(default="gpt-4o-mini", alias="OPENAI_CHAT_MODEL")
    embedding_dimensions: int = Field(default=1536, alias="EMBEDDING_DIMENSIONS")

    vector_index_name: str = "kb_vector_index"
    text_index_name: str = "kb_text_index"
    knowledge_collection: str = "knowledge_base"
    customers_collection: str = "customers"
    accounts_collection: str = "accounts"
    households_collection: str = "households"
    transactions_collection: str = "transactions"
    transcripts_collection: str = "transcripts"
    graph_collection: str = "graph_nodes"
    session_turns_collection: str = "session_turns"
    user_memory_collection: str = "user_memory"
    checkpoints_collection: str = "checkpoints"
    checkpoint_writes_collection: str = "checkpoint_writes"
    audit_logs_collection: str = "ai_audit_logs"
    lineage_collection: str = "answer_lineage"
    memory_vector_index_name: str = "user_memory_vector_index"

    vector_num_candidates: int = 150
    vector_limit: int = 6
    hybrid_vector_weight: float = 0.65
    hybrid_text_weight: float = 0.35

    bank_name: str = "Atlas National Bank"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide Settings singleton.

    ``lru_cache`` avoids re-reading the environment on every request while
    still allowing tests to clear the cache with ``get_settings.cache_clear()``.
    """

    return Settings()
