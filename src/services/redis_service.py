"""
name: redis_service
description: Async Redis service providing sliding window session memory, distributed locking, and LLM response caching.
"""

import hashlib
import json
import logging
import uuid
from typing import Dict, List, Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.config import AIBackend, get_settings

logger = logging.getLogger(__name__)

# Atomic Lua script to safely release a lock only if the token matches
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisService:
    """Manages Redis-backed chat memory, distributed user locks, backend state, and LLM caching."""

    def __init__(self, client: Optional[Redis] = None) -> None:
        """
        Initialize RedisService with an optional injected Redis client for testability.

        Parameters:
            client (Optional[Redis]): Existing async Redis client instance; creates default from settings if None.
        """
        settings = get_settings()
        self._settings = settings
        self._client: Redis = client or Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    async def ping(self) -> bool:
        """
        Verify connectivity to the Redis server.

        Returns:
            bool: True if Redis responds to PING, False otherwise.
        """
        try:
            return bool(await self._client.ping())
        except RedisError as exc:
            logger.warning("Redis ping failed: %s", exc)
            return False

    async def close(self) -> None:
        """Close the underlying Redis connection pool."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Sliding Window Session Memory
    # ------------------------------------------------------------------
    def _history_key(self, user_id: int) -> str:
        return f"chat:history:{user_id}"

    async def get_chat_history(self, user_id: int) -> List[Dict[str, str]]:
        """
        Retrieve the recent sliding-window conversation turns for a user.

        Parameters:
            user_id (int): Telegram user identifier.
        Returns:
            List[Dict[str, str]]: List of turn dicts with 'role' and 'content' keys.
        """
        key = self._history_key(user_id)
        try:
            raw_items = await self._client.lrange(key, 0, -1)
            return [json.loads(item) for item in raw_items]
        except RedisError as exc:
            logger.warning("Failed to get chat history for user %s: %s", user_id, exc)
            return []

    async def append_chat_turn(self, user_id: int, role: str, content: str) -> None:
        """
        Append a single message turn to the user's sliding-window history and refresh TTL.

        Parameters:
            user_id (int): Telegram user identifier.
            role (str): Message role ('human' or 'ai').
            content (str): Message text content.
        """
        key = self._history_key(user_id)
        max_items = self._settings.redis_chat_window_size * 2
        payload = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        try:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.rpush(key, payload)
                pipe.ltrim(key, -max_items, -1)
                pipe.expire(key, self._settings.redis_chat_history_ttl)
                await pipe.execute()
        except RedisError as exc:
            logger.warning("Failed to append chat turn for user %s: %s", user_id, exc)

    async def clear_chat_history(self, user_id: int) -> None:
        """
        Clear stored conversation memory for a user.

        Parameters:
            user_id (int): Telegram user identifier.
        """
        try:
            await self._client.delete(self._history_key(user_id))
        except RedisError as exc:
            logger.warning("Failed to clear chat history for user %s: %s", user_id, exc)

    # ------------------------------------------------------------------
    # Distributed User Lock (Anti-Spam / Concurrency Guard)
    # ------------------------------------------------------------------
    def _lock_key(self, user_id: int) -> str:
        return f"lock:user:{user_id}"

    async def acquire_user_lock(self, user_id: int, ttl_seconds: int = 60) -> Optional[str]:
        """
        Acquire a short-lived distributed lock for a user to prevent concurrent duplicate LLM requests.

        Parameters:
            user_id (int): Telegram user identifier.
            ttl_seconds (int): Auto-expiration timeout in seconds.
        Returns:
            Optional[str]: Unique lock token if acquired, or None if already locked.
        """
        token = str(uuid.uuid4())
        try:
            acquired = await self._client.set(self._lock_key(user_id), token, nx=True, ex=ttl_seconds)
            return token if acquired else None
        except RedisError as exc:
            logger.warning("Redis lock acquisition failed (allowing request): %s", exc)
            return "fallback-token"

    async def release_user_lock(self, user_id: int, token: str) -> None:
        """
        Release a previously acquired user lock safely if the token matches.

        Parameters:
            user_id (int): Telegram user identifier.
            token (str): Lock token returned by acquire_user_lock.
        """
        if token == "fallback-token":
            return
        try:
            await self._client.eval(_RELEASE_LOCK_SCRIPT, 1, self._lock_key(user_id), token)
        except RedisError as exc:
            logger.warning("Failed to release lock for user %s: %s", user_id, exc)

    # ------------------------------------------------------------------
    # LLM Response Cache
    # ------------------------------------------------------------------
    @staticmethod
    def _cache_key(namespace: str, prompt: str) -> str:
        digest = hashlib.sha256(prompt.strip().lower().encode("utf-8")).hexdigest()
        return f"cache:llm:{namespace}:{digest}"

    async def get_cached_llm_response(self, namespace: str, prompt: str) -> Optional[str]:
        """
        Look up a cached LLM response for an identical normalized prompt.

        Parameters:
            namespace (str): Logical cache partition (e.g., 'vocab' or 'chat').
            prompt (str): Normalized user prompt or query string.
        Returns:
            Optional[str]: Cached response string if present, else None.
        """
        try:
            return await self._client.get(self._cache_key(namespace, prompt))
        except RedisError as exc:
            logger.warning("Redis cache read failed: %s", exc)
            return None

    async def set_cached_llm_response(
        self,
        namespace: str,
        prompt: str,
        response: str,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """
        Store an LLM response in Redis with expiration TTL.

        Parameters:
            namespace (str): Logical cache partition.
            prompt (str): Input prompt used as cache key basis.
            response (str): Serialized response payload.
            ttl_seconds (Optional[int]): Optional custom expiration in seconds.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._settings.redis_cache_ttl
        try:
            await self._client.set(self._cache_key(namespace, prompt), response, ex=ttl)
        except RedisError as exc:
            logger.warning("Redis cache write failed: %s", exc)

    # ------------------------------------------------------------------
    # Active AI Backend State
    # ------------------------------------------------------------------
    _BACKEND_KEY = "config:active_ai_backend"

    async def get_active_backend(self) -> AIBackend:
        """
        Fetch the active AI backend override from Redis, falling back to environment config.

        Returns:
            AIBackend: Currently active backend enum value.
        """
        try:
            raw = await self._client.get(self._BACKEND_KEY)
            if raw:
                return AIBackend(raw)
        except (RedisError, ValueError) as exc:
            logger.warning("Failed to read active backend from Redis: %s", exc)
        return self._settings.ai_backend

    async def set_active_backend(self, backend: AIBackend) -> None:
        """
        Persist the active AI backend selection in Redis for dynamic runtime switching.

        Parameters:
            backend (AIBackend): Target backend stage ('gemini', 'ollama', or 'huggingface').
        """
        try:
            await self._client.set(self._BACKEND_KEY, backend.value)
        except RedisError as exc:
            logger.warning("Failed to set active backend in Redis: %s", exc)

