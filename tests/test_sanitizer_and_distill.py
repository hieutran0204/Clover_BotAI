"""
name: test_sanitizer_and_distill
description: Unit tests for bilingual SanitizerService rules and synthetic ShareGPT distillation data generation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.cli.generate_distill_data import generate_distillation_records
from src.db.models import VocabGroundTruth
from src.services.sanitizer_service import SanitizerService


def test_sanitizer_rejects_ai_persona_and_truncation() -> None:
    """
    Verify SanitizerService catches English/Vietnamese AI disclaimers, short replies, and unclosed code fences.
    """
    en_persona = SanitizerService.evaluate_turn(
        prompt="Explain resilient",
        response="As an AI language model, I am happy to tell you that resilient means strong.",
    )
    assert en_persona.passed is False
    assert en_persona.reason == "ai_persona_boilerplate"

    vi_persona = SanitizerService.evaluate_turn(
        prompt="Từ mitigate là gì?",
        response="Là một trí tuệ nhân tạo, tôi không có cảm xúc nhưng mitigate nghĩa là giảm nhẹ.",
    )
    assert vi_persona.passed is False
    assert vi_persona.reason == "ai_persona_boilerplate"

    truncated = SanitizerService.evaluate_turn(
        prompt="Give a code example",
        response="Here is the snippet:\n```python\nprint('hello')\n",
    )
    assert truncated.passed is False
    assert truncated.reason == "truncated_code_fence"

    valid = SanitizerService.evaluate_turn(
        prompt="Từ concise nghĩa là gì?",
        response="Từ concise (/kənˈsaɪs/) nghĩa là ngắn gọn, súc tích mà vẫn đủ ý.",
        turns_json=[
            {"role": "user", "content": "Từ concise nghĩa là gì?"},
            {
                "role": "assistant",
                "content": "Từ concise (/kənˈsaɪs/) nghĩa là ngắn gọn, súc tích mà vẫn đủ ý.",
            },
        ],
    )
    assert valid.passed is True
    assert valid.reason is None


@pytest.mark.asyncio
async def test_generate_distillation_records_creates_verified_golden_rows() -> None:
    """
    Verify VocabGroundTruth records convert cleanly into verified_golden ShareGPT chat_logs.
    """
    vocab = VocabGroundTruth(
        telegram_user_id=None,
        word="pragmatic",
        phonetic="/præɡˈmæt.ɪk/",
        part_of_speech="adjective",
        definition_vi="Thực tế, thực dụng theo hướng hiệu quả",
        definition_en="Dealing with things sensibly and realistically",
        example_sentence="They took a pragmatic approach.",
        example_translation="Họ đã chọn cách tiếp cận thực tế.",
        cefr_level="C1",
        quiz_question="What does pragmatic mean?",
        quiz_options=["Practical", "Imaginary", "Lazy", "Loud"],
        quiz_correct_index=0,
    )

    vocab_result = MagicMock()
    vocab_result.scalars.return_value.all.return_value = [vocab]

    existing_prompts_result = MagicMock()
    existing_prompts_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[vocab_result, existing_prompts_result])
    session.add = MagicMock()
    session.flush = AsyncMock()

    report = await generate_distillation_records(session=session, use_llm=False)

    assert report.examined == 1
    assert report.created_golden == 1
    assert report.rejected_by_sanitizer == 0
    assert session.add.call_count == 1
    inserted_log = session.add.call_args.args[0]
    assert inserted_log.status == "verified_golden"
    assert len(inserted_log.turns_json) == 3
    assert inserted_log.turns_json[0]["role"] == "system"
    assert "pragmatic" in inserted_log.turns_json[2]["content"]

