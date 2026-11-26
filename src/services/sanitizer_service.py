"""
name: sanitizer_service
description: Bilingual AI-persona and quality sanitization gate for filtering ChatLogs into verified_golden distillation data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ChatLogs

MIN_RESPONSE_LENGTH = 20

_AI_PERSONA_PATTERNS = (
    re.compile(r"\bas an ai\b", re.IGNORECASE),
    re.compile(r"\bi am a language model\b", re.IGNORECASE),
    re.compile(r"\bas a (?:large )?language model\b", re.IGNORECASE),
    re.compile(r"\btrained by (?:google|openai|anthropic)\b", re.IGNORECASE),
    re.compile(r"\bi don'?t have personal\b", re.IGNORECASE),
    re.compile(r"tôi là (?:một )?mô hình ngôn ngữ", re.IGNORECASE),
    re.compile(r"là một (?:trí tuệ nhân tạo|ai\b)", re.IGNORECASE),
    re.compile(r"tôi không có (?:cảm xúc|trải nghiệm cá nhân)", re.IGNORECASE),
    re.compile(r"được huấn luyện bởi (?:google|openai)", re.IGNORECASE),
)

_REFUSAL_AND_ERROR_PATTERNS = (
    re.compile(r"xin lỗi,\s*mình đang gặp sự cố kết nối ai", re.IGNORECASE),
    re.compile(r"\bi'?m sorry,?\s*(?:but\s*)?i cannot\b", re.IGNORECASE),
    re.compile(r"\bi cannot fulfill this request\b", re.IGNORECASE),
)


@dataclass
class SanitizationDecision:
    """
    Result of running quality and persona filters over a single conversation turn.
    """

    passed: bool
    reason: Optional[str] = None
    cleaned_response: str = ""
    cleaned_turns: Optional[List[Dict[str, Any]]] = None


@dataclass
class SanitizationStats:
    """
    Aggregate counters produced by sanitizing pending `chat_logs` rows.
    """

    total_scanned: int = 0
    verified: int = 0
    rejected: int = 0
    rejection_breakdown: Dict[str, int] = field(default_factory=dict)


class SanitizerService:
    """
    Clean and validate ChatLogs conversations before promoting them to `verified_golden`.
    """

    @staticmethod
    def _clean_text(text: str) -> str:
        """
        Normalize excessive blank lines and trailing whitespace without altering markdown structure.

        Parameters:
            text (str): Raw prompt or response text.

        Returns:
            str: Cleaned text string.
        """
        normalized = text.replace("\r\n", "\n").strip()
        return re.sub(r"\n{3,}", "\n\n", normalized)

    @classmethod
    def evaluate_turn(
        cls,
        prompt: str,
        response: str,
        turns_json: Optional[List[Dict[str, Any]]] = None,
    ) -> SanitizationDecision:
        """
        Evaluate a conversation turn against emptiness, truncation, error-fallback, and AI-persona rules.

        Parameters:
            prompt (str): User prompt text.
            response (str): Assistant response text.
            turns_json (Optional[List[Dict[str, Any]]]): Optional multi-turn message list.

        Returns:
            SanitizationDecision: Decision containing pass/fail flag, rejection reason, and cleaned payloads.
        """
        cleaned_prompt = cls._clean_text(prompt or "")
        cleaned_response = cls._clean_text(response or "")

        if not cleaned_prompt:
            return SanitizationDecision(passed=False, reason="empty_prompt")

        if len(cleaned_response) < MIN_RESPONSE_LENGTH:
            return SanitizationDecision(
                passed=False,
                reason="response_too_short",
                cleaned_response=cleaned_response,
            )

        if cleaned_response.count("```") % 2 != 0:
            return SanitizationDecision(
                passed=False,
                reason="truncated_code_fence",
                cleaned_response=cleaned_response,
            )

        for pattern in _REFUSAL_AND_ERROR_PATTERNS:
            if pattern.search(cleaned_response):
                return SanitizationDecision(
                    passed=False,
                    reason="error_or_refusal_fallback",
                    cleaned_response=cleaned_response,
                )

        for pattern in _AI_PERSONA_PATTERNS:
            if pattern.search(cleaned_response):
                return SanitizationDecision(
                    passed=False,
                    reason="ai_persona_boilerplate",
                    cleaned_response=cleaned_response,
                )

        cleaned_turns: Optional[List[Dict[str, Any]]] = None
        if turns_json is not None:
            cleaned_turns = [
                {
                    "role": str(turn.get("role") or turn.get("from") or "").strip(),
                    "content": cls._clean_text(str(turn.get("content") or turn.get("value") or "")),
                }
                for turn in turns_json
                if str(turn.get("content") or turn.get("value") or "").strip()
            ]
            if len(cleaned_turns) < 2:
                return SanitizationDecision(
                    passed=False,
                    reason="insufficient_turns",
                    cleaned_response=cleaned_response,
                    cleaned_turns=cleaned_turns,
                )

        return SanitizationDecision(
            passed=True,
            reason=None,
            cleaned_response=cleaned_response,
            cleaned_turns=cleaned_turns,
        )

    @classmethod
    async def sanitize_pending_logs(
        cls,
        session: AsyncSession,
        limit: int = 500,
    ) -> SanitizationStats:
        """
        Inspect pending `raw` rows in `chat_logs` and transition each to `verified_golden` or `rejected`.

        Parameters:
            session (AsyncSession): Active database session.
            limit (int): Maximum number of raw rows inspected per batch.

        Returns:
            SanitizationStats: Counters for scanned, verified, and rejected records.
        """
        stmt = (
            select(ChatLogs)
            .where(ChatLogs.status == "raw")
            .order_by(ChatLogs.created_at.asc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()

        stats = SanitizationStats()
        for row in rows:
            stats.total_scanned += 1
            decision = cls.evaluate_turn(
                prompt=row.prompt,
                response=row.response,
                turns_json=row.turns_json,
            )
            if decision.passed:
                row.status = "verified_golden"
                row.rejection_reason = None
                row.response = decision.cleaned_response
                if decision.cleaned_turns is not None:
                    row.turns_json = decision.cleaned_turns
                stats.verified += 1
            else:
                reason = decision.reason or "validation_failed"
                row.status = "rejected"
                row.rejection_reason = reason
                stats.rejected += 1
                stats.rejection_breakdown[reason] = stats.rejection_breakdown.get(reason, 0) + 1

        await session.flush()
        return stats

