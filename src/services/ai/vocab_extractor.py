"""
name: vocab_extractor
description: Passive vocabulary extraction service analyzing completed chat turns to populate ground truth.
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from src.core.config import AIBackend
from src.schemas.vocab import VocabBatchSchema
from src.services.ai.llm_factory import LLMFactory
from src.services.redis_service import RedisService

logger = logging.getLogger(__name__)

_TRIVIAL_MESSAGES = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "ok",
        "okay",
        "yes",
        "no",
        "thanks",
        "thank you",
        "bye",
        "goodbye",
        "chào",
        "xin chào",
        "cảm ơn",
        "ừ",
        "ờ",
    }
)

VOCAB_EXTRACTION_PROMPT = """Analyze this English-learning conversation turn between a learner and an AI tutor.
Extract up to 3 useful English vocabulary words or idioms (CEFR B1-C2, business, academic, technical, or words the learner explicitly asked about) worth saving for Spaced Repetition review.

Rules:
- If the turn is purely casual greeting, acknowledgment, or contains no notable English vocabulary worth studying, return an empty list: items=[].
- Normalize each extracted word/phrase in lowercase singular/base form where appropriate.
- Do NOT invent words unrelated to the conversation turn.
- Every item must include phonetic IPA, part_of_speech, Vietnamese definition (definition_vi), concise English definition (definition_en), natural example_sentence + Vietnamese translation, CEFR level (A1-C2), and a 4-option multiple choice quiz (quiz_options length 4, quiz_correct_index 0..3).

Learner message:
{user_message}

Tutor reply:
{bot_reply}"""


class VocabExtractorService:
    """
    Extract learnable English vocabulary asynchronously from conversational turns.
    """

    def __init__(self, redis_service: Optional[RedisService] = None) -> None:
        """
        Initialize the passive vocabulary extractor.

        Parameters:
            redis_service (Optional[RedisService]): Optional Redis service to inspect active AI backend.
        """
        self._redis_service = redis_service

    @staticmethod
    def is_trivial_message(user_message: str) -> bool:
        """
        Determine whether a user message is too trivial to warrant LLM vocabulary extraction.

        Parameters:
            user_message (str): Raw user input text.

        Returns:
            bool: True if the message is empty or a simple conversational filler.
        """
        normalized = " ".join(user_message.strip().lower().split()).rstrip("!.?,")
        if len(normalized) < 2:
            return True
        return normalized in _TRIVIAL_MESSAGES

    async def extract_from_turn(
        self,
        user_message: str,
        bot_reply: str,
        backend: Optional[AIBackend] = None,
    ) -> VocabBatchSchema:
        """
        Inspect a `(user_message, bot_reply)` turn and return notable vocabulary items.

        Parameters:
            user_message (str): Message sent by the Telegram learner.
            bot_reply (str): Response produced by the AI tutor.
            backend (Optional[AIBackend]): Optional AI backend override.

        Returns:
            VocabBatchSchema: Extracted vocabulary batch (empty list when nothing notable is found).
        """
        if self.is_trivial_message(user_message):
            return VocabBatchSchema(items=[])

        selected_backend = backend
        if selected_backend is None and self._redis_service is not None:
            selected_backend = await self._redis_service.get_active_backend()

        llm, _ = LLMFactory.get_chat_model(backend=selected_backend, temperature=0.2)
        structured_llm = llm.with_structured_output(VocabBatchSchema)

        prompt_text = VOCAB_EXTRACTION_PROMPT.format(
            user_message=user_message[:1500],
            bot_reply=bot_reply[:2000],
        )
        result = await structured_llm.ainvoke(
            [
                SystemMessage(
                    content="You are an English curriculum analyst extracting study-worthy vocabulary."
                ),
                HumanMessage(content=prompt_text),
            ]
        )
        if not isinstance(result, VocabBatchSchema):
            return VocabBatchSchema.model_validate(result)
        return result

