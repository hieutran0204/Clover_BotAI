"""
name: config
description: Centralized application configuration loaded from environment variables using Pydantic Settings.
"""

from enum import Enum
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIBackend(str, Enum):
    """Supported AI backend stages in the 3-stage knowledge distillation pipeline."""

    GEMINI = "gemini"
    OLLAMA = "ollama"
    HUGGINGFACE = "huggingface"


class EmbeddingProvider(str, Enum):
    """Supported embedding model providers."""

    GEMINI = "gemini"
    OLLAMA = "ollama"


class Settings(BaseSettings):
    """Application settings validated from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Storage Portability
    data_dir: str = Field(default="./data", description="Root directory for persistent storage")

    # Telegram Bot
    telegram_bot_token: str = Field(default="", description="Telegram Bot API token")
    admin_user_ids: List[int] = Field(default_factory=list, description="List of admin Telegram IDs")
    max_telegram_file_mb: int = Field(
        default=50, description="Maximum attachment file size in megabytes (MB) allowed for processing"
    )

    @property
    def max_telegram_file_bytes(self) -> int:
        """Return maximum telegram file size in bytes."""
        return self.max_telegram_file_mb * 1024 * 1024

    # 3-Stage AI Backend
    ai_backend: AIBackend = Field(default=AIBackend.GEMINI, description="Active AI model backend")

    # Stage 1: Gemini Teacher
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    gemini_model: str = Field(default="gemini-3.6-flash", description="Gemini model identifier")
    gemini_embedding_model: str = Field(
        default="models/gemini-embedding-001", description="Gemini embedding model identifier"
    )
    embedding_dimensions: int = Field(
        default=768, description="Vector dimension matching pgvector schema"
    )
    embedding_provider: EmbeddingProvider = Field(
        default=EmbeddingProvider.OLLAMA, description="Active embedding provider ('ollama' or 'gemini')"
    )
    ollama_embedding_model: str = Field(
        default="nomic-embed-text", description="Ollama embedding model name"
    )

    # Hybrid RAG & Reranker
    rag_candidate_k: int = Field(default=15, description="Number of candidates from hybrid retrieval")
    rag_top_k: int = Field(default=3, description="Number of top reranked records")
    rag_reranker_threshold: float = Field(default=0.35, description="Cross-encoder reranker HIT threshold")
    rag_reranker_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2", description="Cross-encoder model name"
    )

    # Stage 2: Open Source via Ollama
    ollama_base_url: str = Field(default="http://ollama:11434", description="Ollama server base URL")
    ollama_model: str = Field(default="qwen2.5:7b", description="Default Ollama model name")

    @property
    def resolved_ollama_base_url(self) -> str:
        """Resolve Ollama base URL safely when running outside Docker container on host."""
        import os
        if "host.docker.internal" in self.ollama_base_url and not os.path.exists("/.dockerenv"):
            return self.ollama_base_url.replace("host.docker.internal", "127.0.0.1")
        return self.ollama_base_url

    # Stage 3: Hugging Face / vLLM Serving
    hf_model_id: str = Field(default="Qwen/Qwen2.5-7B-Instruct", description="Hugging Face model ID")
    hf_serving_url: str = Field(default="http://vllm:8000/v1", description="OpenAI-compatible vLLM endpoint")
    hf_api_key: str = Field(default="EMPTY", description="API key for local vLLM/HF server")

    # PostgreSQL + pgvector
    postgres_user: str = Field(default="postgres")
    postgres_password: str = Field(default="postgres_secret_change_me")
    postgres_db: str = Field(default="ai_telegram")
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres_secret_change_me@postgres:5432/ai_telegram",
        description="Async SQLAlchemy database connection string",
    )

    # Redis
    redis_host: str = Field(default="redis")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_url: str = Field(default="redis://redis:6379/0", description="Redis connection URL")
    redis_chat_history_ttl: int = Field(default=86400, description="Session sliding window TTL in seconds")
    redis_chat_window_size: int = Field(default=10, description="Max turns stored in Redis sliding window")
    redis_cache_ttl: int = Field(default=3600, description="LLM response cache TTL in seconds")

    # Jobs & Logging
    vocab_quiz_interval_seconds: int = Field(default=300, description="Interval in seconds for quiz job")
    log_level: str = Field(default="INFO", description="Application logging level")

    # Web Admin Dashboard (FastAPI + SQLAdmin)
    admin_username: str = Field(default="admin", description="Admin dashboard login username")
    admin_password: str = Field(default="admin123456", description="Admin dashboard login password")
    admin_secret_key: str = Field(
        default="admin_session_secret_key_change_me_in_production_32bytes",
        description="Secret key for signing admin session cookies",
    )
    admin_port: int = Field(default=8000, description="Web Admin HTTP listening port")

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> List[int]:
        """
        Parse comma-separated admin user IDs from environment string or pass through lists.

        Parameters:
            value (object): Raw input from environment variable or initialization.
        Returns:
            List[int]: List of integer Telegram user IDs.
        """
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        if isinstance(value, int):
            return [value]
        if isinstance(value, list):
            return [int(item) for item in value]
        return []


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached singleton instance of application settings.

    Returns:
        Settings: Validated application configuration object.
    """
    return Settings()

