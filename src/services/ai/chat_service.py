"""
name: chat_service
description: LangChain orchestration service for structured vocabulary generation and multi-turn conversations.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import AIBackend
from src.schemas.vocab import VocabBatchSchema, VocabSchema
from src.services.ai.llm_factory import LLMFactory
from src.services.redis_service import RedisService

logger = logging.getLogger(__name__)

TEACHER_SYSTEM_PROMPT = (
    "You are a friendly, natural bilingual English study buddy chatting on Telegram. "
    "Explain concepts concisely, use everyday examples, and avoid robotic AI disclaimers "
    "(never say 'As an AI language model' or 'Tôi là trợ lý AI'). "
    "Keep replies engaging, warm, and practical."
)

VOCAB_GENERATION_PROMPT = (
    "Generate one high-value English vocabulary item related to the topic: '{topic}'. "
    "Provide accurate IPA phonetics, natural Vietnamese and English definitions, "
    "a realistic example sentence with Vietnamese translation, and a 4-option multiple-choice quiz."
)

VOCAB_BATCH_PROMPT = (
    "Generate {count} distinct, high-value English vocabulary items (CEFR B1 to C2) "
    "for the topic: '{topic}'. Do NOT include any of these already-known words: {exclude_words}. "
    "For each item, provide accurate IPA phonetics, clear Vietnamese & English definitions, "
    "a realistic everyday example sentence with Vietnamese translation, and a 4-option quiz."
)

VOCAB_ENRICH_PROMPT = (
    "Create complete structured vocabulary lessons and 4-option quizzes for each of these exact "
    "English words (topic context: '{topic}'): {words}. "
    "Keep each target word unchanged and provide accurate IPA, definitions, examples, and quiz."
)


class AIChatService:
    """Orchestrates LLM calls via LangChain with Redis session memory and structured outputs."""

    def __init__(self, redis_service: RedisService) -> None:
        """
        Initialize AIChatService with a RedisService dependency.

        Parameters:
            redis_service (RedisService): Service managing sliding-window memory and query cache.
        """
        self._redis = redis_service

    @staticmethod
    def _build_langchain_messages(
        history: List[Dict[str, str]],
        user_message: str,
    ) -> List[BaseMessage]:
        """
        Convert raw history turns and the new prompt into LangChain message objects.

        Parameters:
            history (List[Dict[str, str]]): Prior turns retrieved from Redis.
            user_message (str): Incoming message from the Telegram user.
        Returns:
            List[BaseMessage]: Ordered list starting with SystemMessage followed by turns.
        """
        messages: List[BaseMessage] = [SystemMessage(content=TEACHER_SYSTEM_PROMPT)]
        for turn in history:
            role = turn.get("role")
            content = turn.get("content", "")
            if role == "human":
                messages.append(HumanMessage(content=content))
            elif role == "ai":
                messages.append(AIMessage(content=content))
        messages.append(HumanMessage(content=user_message))
        return messages

    @staticmethod
    def _to_sharegpt_turns(
        history: List[Dict[str, str]],
        user_message: str,
        ai_response: str,
    ) -> List[Dict[str, Any]]:
        """
        Serialize the interaction window into ChatML multi-turn JSON format.

        Parameters:
            history (List[Dict[str, str]]): Prior conversation turns.
            user_message (str): Current human prompt.
            ai_response (str): Assistant response text.
        Returns:
            List[Dict[str, Any]]: ChatML conversation turns list with role and content keys.
        """
        turns: List[Dict[str, Any]] = []
        for turn in history:
            role = "user" if turn.get("role") == "human" else "assistant"
            turns.append({"role": role, "content": turn.get("content", "")})
        turns.append({"role": "user", "content": user_message})
        turns.append({"role": "assistant", "content": ai_response})
        return turns

    @staticmethod
    def _extract_text_content(content: object) -> str:
        """
        Extract clean plain text from an LLM response content string or structured block list.

        Parameters:
            content (object): AIMessage.content (str or list of content block dicts).
        Returns:
            str: Concatenated plain text response without signature metadata.
        """
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    text_val = item.get("text")
                    if text_val:
                        parts.append(str(text_val))
            return "\n".join(parts).strip()
        return str(content).strip()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6), reraise=True)
    async def generate_vocab_item(
        self,
        topic: str = "daily communication",
        backend: Optional[AIBackend] = None,
    ) -> Tuple[VocabSchema, str]:
        """
        Generate a structured vocabulary lesson and quiz validated against VocabSchema.

        Parameters:
            topic (str): Topic keyword to guide vocabulary selection.
            backend (Optional[AIBackend]): Optional backend override; uses active Redis/config backend if None.
        Returns:
            Tuple[VocabSchema, str]: Validated VocabSchema object and model name used.
        """
        active_backend = backend or await self._redis.get_active_backend()
        model, model_name = LLMFactory.get_chat_model(backend=active_backend, temperature=0.4)

        structured_llm = model.with_structured_output(VocabSchema)
        prompt_text = VOCAB_GENERATION_PROMPT.format(topic=topic)
        result = await structured_llm.ainvoke(
            [
                SystemMessage(content=TEACHER_SYSTEM_PROMPT),
                HumanMessage(content=prompt_text),
            ]
        )
        if not isinstance(result, VocabSchema):
            result = VocabSchema.model_validate(result)
        return result, model_name

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6), reraise=True)
    async def generate_vocab_batch(
        self,
        topic: str,
        count: int = 5,
        exclude_words: Optional[List[str]] = None,
        backend: Optional[AIBackend] = None,
    ) -> Tuple[VocabBatchSchema, str]:
        """
        Generate a batch of distinct vocabulary items for a topic while excluding existing DB words.

        Parameters:
            topic (str): Target topic for vocabulary generation.
            count (int): Desired number of new vocabulary entries.
            exclude_words (Optional[List[str]]): Existing words to exclude from generation.
            backend (Optional[AIBackend]): Optional AI backend override.
        Returns:
            Tuple[VocabBatchSchema, str]: Validated batch of VocabSchema entries and model name.
        """
        active_backend = backend or await self._redis.get_active_backend()
        model, model_name = LLMFactory.get_chat_model(backend=active_backend, temperature=0.5)
        structured_llm = model.with_structured_output(VocabBatchSchema)

        excluded = ", ".join(sorted(exclude_words)[:150]) if exclude_words else "none"
        prompt_text = VOCAB_BATCH_PROMPT.format(
            count=count,
            topic=topic,
            exclude_words=excluded,
        )
        result = await structured_llm.ainvoke(
            [
                SystemMessage(content=TEACHER_SYSTEM_PROMPT),
                HumanMessage(content=prompt_text),
            ]
        )
        if not isinstance(result, VocabBatchSchema):
            result = VocabBatchSchema.model_validate(result)
        return result, model_name

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6), reraise=True)
    async def enrich_raw_words(
        self,
        words: List[str],
        topic: str = "general",
        backend: Optional[AIBackend] = None,
    ) -> Tuple[VocabBatchSchema, str]:
        """
        Enrich raw English word strings into complete structured VocabSchema entries.

        Parameters:
            words (List[str]): Raw target English words to enrich.
            topic (str): Optional topic context for definitions and examples.
            backend (Optional[AIBackend]): Optional AI backend override.
        Returns:
            Tuple[VocabBatchSchema, str]: Validated VocabBatchSchema and model name.
        """
        if not words:
            return VocabBatchSchema(items=[]), "none"

        active_backend = backend or await self._redis.get_active_backend()
        model, model_name = LLMFactory.get_chat_model(backend=active_backend, temperature=0.3)
        structured_llm = model.with_structured_output(VocabBatchSchema)

        prompt_text = VOCAB_ENRICH_PROMPT.format(
            topic=topic,
            words=", ".join(words),
        )
        result = await structured_llm.ainvoke(
            [
                SystemMessage(content=TEACHER_SYSTEM_PROMPT),
                HumanMessage(content=prompt_text),
            ]
        )
        if not isinstance(result, VocabBatchSchema):
            result = VocabBatchSchema.model_validate(result)
        return result, model_name

    async def chat_with_context(
        self,
        user_id: int,
        user_message: str,
        backend: Optional[AIBackend] = None,
    ) -> Tuple[str, List[Dict[str, Any]], AIBackend, str]:
        """
        Generate a contextual response using Redis sliding-window memory and update session history.

        Parameters:
            user_id (int): Telegram user identifier.
            user_message (str): Incoming message text.
            backend (Optional[AIBackend]): Optional AI backend override.
        Returns:
            Tuple[str, List[Dict[str, Any]], AIBackend, str]:
                Reply text, ShareGPT turns list, backend used, and model name.
        """
        active_backend = backend or await self._redis.get_active_backend()
        history = await self._redis.get_chat_history(user_id)

        # Check response cache only when there is no prior conversational context
        if not history:
            cached = await self._redis.get_cached_llm_response(active_backend.value, user_message)
            if cached:
                await self._redis.append_chat_turn(user_id, "human", user_message)
                await self._redis.append_chat_turn(user_id, "ai", cached)
                turns = self._to_sharegpt_turns(history, user_message, cached)
                return cached, turns, active_backend, "cache"

        model, model_name = LLMFactory.get_chat_model(backend=active_backend, temperature=0.7)
        messages = self._build_langchain_messages(history, user_message)

        ai_msg = await model.ainvoke(messages)
        reply_text = self._extract_text_content(ai_msg.content)

        await self._redis.append_chat_turn(user_id, "human", user_message)
        await self._redis.append_chat_turn(user_id, "ai", reply_text)

        if not history:
            await self._redis.set_cached_llm_response(active_backend.value, user_message, reply_text)

        turns = self._to_sharegpt_turns(history, user_message, reply_text)
        return reply_text, turns, active_backend, model_name

