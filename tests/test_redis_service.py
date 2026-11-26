"""
name: test_redis_service
description: Unit tests for RedisService sliding-window memory, distributed locking, and LLM caching.
"""

from typing import Any, Dict, List

from src.core.config import AIBackend
from src.services.redis_service import RedisService


class _FakePipeline:
    """In-memory async pipeline stub mirroring redis.asyncio pipeline calls."""

    def __init__(self, store: "_FakeRedis") -> None:
        self._store = store
        self._ops: List[Any] = []

    async def __aenter__(self) -> "_FakePipeline":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def rpush(self, key: str, value: str) -> None:
        self._ops.append(("rpush", key, value))

    def ltrim(self, key: str, start: int, end: int) -> None:
        self._ops.append(("ltrim", key, start, end))

    def expire(self, key: str, ttl: int) -> None:
        self._ops.append(("expire", key, ttl))

    async def execute(self) -> List[Any]:
        results = []
        for op in self._ops:
            cmd = op[0]
            if cmd == "rpush":
                lst = self._store.lists.setdefault(op[1], [])
                lst.append(op[2])
                results.append(len(lst))
            elif cmd == "ltrim":
                lst = self._store.lists.get(op[1], [])
                start, end = op[2], op[3]
                if end == -1:
                    self._store.lists[op[1]] = lst[start:]
                else:
                    self._store.lists[op[1]] = lst[start : end + 1]
                results.append(True)
            elif cmd == "expire":
                self._store.ttls[op[1]] = op[2]
                results.append(True)
        return results


class _FakeRedis:
    """In-memory async Redis stub supporting strings, lists, locks, and Lua eval."""

    def __init__(self) -> None:
        self.kv: Dict[str, str] = {}
        self.lists: Dict[str, List[str]] = {}
        self.ttls: Dict[str, int] = {}

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self)

    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        lst = self.lists.get(key, [])
        return lst[start:] if end == -1 else lst[start : end + 1]

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, key: str) -> int:
        existed = int(key in self.kv or key in self.lists)
        self.kv.pop(key, None)
        self.lists.pop(key, None)
        return existed

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        if self.kv.get(key) == token:
            del self.kv[key]
            return 1
        return 0


async def test_sliding_window_history_and_clear() -> None:
    """Verify chat history stores turns in order and clears cleanly."""
    service = RedisService(client=_FakeRedis())  # type: ignore[arg-type]
    await service.append_chat_turn(100, "human", "Hello")
    await service.append_chat_turn(100, "ai", "Hi there!")

    history = await service.get_chat_history(100)
    assert history == [
        {"role": "human", "content": "Hello"},
        {"role": "ai", "content": "Hi there!"},
    ]

    await service.clear_chat_history(100)
    assert await service.get_chat_history(100) == []


async def test_distributed_user_lock_prevents_concurrent_access() -> None:
    """Verify second lock attempt fails until owner releases the lock."""
    service = RedisService(client=_FakeRedis())  # type: ignore[arg-type]

    token = await service.acquire_user_lock(42)
    assert token is not None
    assert await service.acquire_user_lock(42) is None

    # Wrong token must not release the lock
    await service.release_user_lock(42, "wrong-token")
    assert await service.acquire_user_lock(42) is None

    # Correct token releases the lock
    await service.release_user_lock(42, token)
    assert await service.acquire_user_lock(42) is not None


async def test_llm_cache_and_backend_override() -> None:
    """Verify exact-match response caching and dynamic AI backend state."""
    service = RedisService(client=_FakeRedis())  # type: ignore[arg-type]

    await service.set_cached_llm_response("gemini", "  What is resilient? ", "Able to bounce back.")
    hit = await service.get_cached_llm_response("gemini", "what is resilient?")
    assert hit == "Able to bounce back."

    await service.set_active_backend(AIBackend.OLLAMA)
    assert await service.get_active_backend() == AIBackend.OLLAMA

