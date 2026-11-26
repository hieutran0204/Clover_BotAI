"""
name: test_llm_factory
description: Unit tests for LLMFactory 3-stage instantiation and AIChatService orchestration.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from src.core.config import AIBackend, Settings
from src.schemas.vocab import VocabSchema
from src.services.ai.chat_service import AIChatService
from src.services.ai.llm_factory import LLMFactory
from src.services.redis_service import RedisService
from tests.test_redis_service import _FakeRedis


def test_llm_factory_instantiates_all_three_stages() -> None:
    """Verify LLMFactory returns the expected LangChain model class for Gemini, Ollama, and Hugging Face."""
    settings = Settings(
        gemini_api_key="fake-gemini-key",
        ollama_base_url="http://localhost:11434",
        ollama_model="qwen2.5:7b",
        hf_model_id="Qwen/Qwen2.5-7B-Instruct",
        hf_serving_url="http://localhost:8000/v1",
        _env_file=None,
    )

    gemini_model, gemini_name = LLMFactory.get_chat_model(AIBackend.GEMINI, settings=settings)
    assert isinstance(gemini_model, ChatGoogleGenerativeAI)
    assert gemini_name == settings.gemini_model

    ollama_model, ollama_name = LLMFactory.get_chat_model(AIBackend.OLLAMA, settings=settings)
    assert isinstance(ollama_model, ChatOllama)
    assert ollama_name == "qwen2.5:7b"

    hf_model, hf_name = LLMFactory.get_chat_model(AIBackend.HUGGINGFACE, settings=settings)
    assert isinstance(hf_model, ChatOpenAI)
    assert hf_name == "Qwen/Qwen2.5-7B-Instruct"


def test_llm_factory_requires_gemini_key() -> None:
    """Verify LLMFactory raises ValueError when Gemini is selected without an API key."""
    settings = Settings(gemini_api_key="", _env_file=None)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        LLMFactory.get_chat_model(AIBackend.GEMINI, settings=settings)


async def test_ai_chat_service_generates_vocab_and_sharegpt_turns() -> None:
    """Verify AIChatService returns validated VocabSchema and serializes ShareGPT conversation logs."""
    redis_service = RedisService(client=_FakeRedis())  # type: ignore[arg-type]
    await redis_service.set_active_backend(AIBackend.OLLAMA)
    chat_service = AIChatService(redis_service=redis_service)

    sample_vocab = VocabSchema(
        word="pragmatic",
        phonetic="/præɡˈmæt.ɪk/",
        part_of_speech="adjective",
        definition_vi="thực tế, thực dụng",
        definition_en="dealing with things sensibly and realistically",
        example_sentence="We need a pragmatic approach to solve this bug.",
        example_translation="Chúng ta cần một cách tiếp cận thực tế để sửa lỗi này.",
        cefr_level="B2",
        quiz_question="What best describes a pragmatic person?",
        quiz_options=["idealistic", "practical and realistic", "indecisive", "reckless"],
        quiz_correct_index=1,
    )

    mock_model = MagicMock()
    mock_structured = MagicMock()
    mock_structured.ainvoke = AsyncMock(return_value=sample_vocab)
    mock_model.with_structured_output.return_value = mock_structured
    mock_model.ainvoke = AsyncMock(return_value=AIMessage(content="Sure! Let's practice together."))

    with patch("src.services.ai.chat_service.LLMFactory.get_chat_model", return_value=(mock_model, "qwen2.5:7b")):
        vocab, model_name = await chat_service.generate_vocab_item("software")
        assert vocab.word == "pragmatic"
        assert model_name == "qwen2.5:7b"

        reply, turns, backend, chat_model = await chat_service.chat_with_context(
            user_id=999,
            user_message="Hey, teach me something!",
        )
        assert reply == "Sure! Let's practice together."
        assert backend == AIBackend.OLLAMA
        assert chat_model == "qwen2.5:7b"
        assert turns == [
            {"role": "user", "content": "Hey, teach me something!"},
            {"role": "assistant", "content": "Sure! Let's practice together."},
        ]


def test_extract_text_content_handles_structured_blocks() -> None:
    """Verify _extract_text_content strips signature metadata from Gemini 3.8 list blocks."""
    raw = [{"type": "text", "text": "Hi there, friend!", "extras": {"signature": "abc123"}}]
    assert AIChatService._extract_text_content(raw) == "Hi there, friend!"
    assert AIChatService._extract_text_content("Plain reply") == "Plain reply"

