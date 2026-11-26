"""
name: teacher_prompts
description: ShareGPT conversation builders converting verified vocabulary ground truth into bilingual tutor dialogues.
"""

from __future__ import annotations

from typing import Dict, List

from src.db.models import VocabGroundTruth

DISTILL_SYSTEM_PROMPT = (
    "You are an encouraging, concise bilingual English-Vietnamese language tutor. "
    "Explain English vocabulary clearly using phonetic IPA, natural context examples, "
    "Vietnamese translation, and practical usage tips without robotic AI disclaimers."
)

LLM_DISTILL_REWRITE_PROMPT = """Rewrite a natural bilingual English-Vietnamese tutoring dialogue about the word '{word}' ({cefr_level}, {part_of_speech}).
Use these verified facts accurately:
- Phonetic: {phonetic}
- Vietnamese meaning: {definition_vi}
- English definition: {definition_en}
- Example: {example_sentence} ({example_translation})

Output ONLY the tutor's clear, encouraging Vietnamese+English explanation (100-180 words). Do not mention being an AI or language model."""


def build_distill_prompt(vocab: VocabGroundTruth) -> str:
    """
    Generate a natural learner question prompt for a ground-truth vocabulary entry.

    Parameters:
        vocab (VocabGroundTruth): Ground-truth vocabulary ORM row.

    Returns:
        str: Realistic learner question in Vietnamese/English.
    """
    return (
        f"Từ '{vocab.word}' ({vocab.part_of_speech}, mức {vocab.cefr_level}) nghĩa là gì vậy, "
        f"và dùng trong câu giao tiếp/công việc như thế nào cho tự nhiên?"
    )


def build_grounded_tutor_response(vocab: VocabGroundTruth) -> str:
    """
    Construct a structured, high-quality bilingual tutor response directly from verified ground-truth fields.

    Parameters:
        vocab (VocabGroundTruth): Ground-truth vocabulary ORM row.

    Returns:
        str: Natural bilingual tutor explanation suitable for SFT/Distillation.
    """
    phonetic_part = f" {vocab.phonetic}" if vocab.phonetic else ""
    translation_line = (
        f"\n↳ Nghĩa: {vocab.example_translation}" if vocab.example_translation else ""
    )
    return (
        f"Từ **{vocab.word}**{phonetic_part} ({vocab.part_of_speech}, CEFR {vocab.cefr_level}) "
        f"nghĩa tiếng Việt là **{vocab.definition_vi}**.\n\n"
        f"- **Giải thích tiếng Anh:** {vocab.definition_en}\n"
        f"- **Ví dụ tự nhiên:** *\"{vocab.example_sentence}\"*{translation_line}\n"
        f"- **Mẹo ghi nhớ & kiểm tra nhanh:** {vocab.quiz_question}"
    )


def build_sharegpt_turns(user_prompt: str, assistant_reply: str) -> List[Dict[str, str]]:
    """
    Format a bilingual tutoring interaction into standard ShareGPT `turns_json` structure.

    Parameters:
        user_prompt (str): Learner question text.
        assistant_reply (str): Clean bilingual tutor explanation.

    Returns:
        List[Dict[str, str]]: List of role/content messages (`system`, `user`, `assistant`).
    """
    return [
        {"role": "system", "content": DISTILL_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": assistant_reply},
    ]

