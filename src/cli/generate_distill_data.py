"""
name: generate_distill_data
description: CLI script converting verified vocab_ground_truth rows into ShareGPT distillation pairs in chat_logs.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import AIBackend
from src.db.models import ChatLogs, VocabGroundTruth
from src.db.session import get_db_session
from src.prompts.teacher_prompts import (
    DISTILL_SYSTEM_PROMPT,
    LLM_DISTILL_REWRITE_PROMPT,
    build_distill_prompt,
    build_grounded_tutor_response,
    build_sharegpt_turns,
)
from src.services.ai.chat_service import AIChatService
from src.services.ai.llm_factory import LLMFactory
from src.services.sanitizer_service import SanitizerService


@dataclass
class DistillGenerationReport:
    """
    Counters summarizing synthetic ShareGPT distillation dataset generation.
    """

    examined: int = 0
    created_golden: int = 0
    skipped_existing: int = 0
    rejected_by_sanitizer: int = 0


async def generate_distillation_records(
    session: AsyncSession,
    limit: Optional[int] = None,
    cefr_filter: Optional[str] = None,
    use_llm: bool = False,
) -> DistillGenerationReport:
    """
    Convert ground-truth vocabulary entries into sanitized ShareGPT dialogues stored in `chat_logs`.

    Parameters:
        session (AsyncSession): Active async SQLAlchemy database session.
        limit (Optional[int]): Optional cap on how many vocab rows to inspect.
        cefr_filter (Optional[str]): Optional CEFR filter (e.g., `B2`, `C1`).
        use_llm (bool): When True, ask Gemini Teacher LLM to paraphrase each grounded explanation.

    Returns:
        DistillGenerationReport: Summary counts of examined, inserted golden, skipped, and rejected turns.
    """
    stmt = select(VocabGroundTruth).order_by(VocabGroundTruth.created_at.asc())
    if cefr_filter:
        stmt = stmt.where(VocabGroundTruth.cefr_level == cefr_filter.strip().upper())
    if limit is not None:
        stmt = stmt.limit(limit)

    vocab_rows = (await session.execute(stmt)).scalars().all()
    existing_prompts = set(
        (await session.execute(select(ChatLogs.prompt))).scalars().all()
    )

    llm = None
    model_name = "ground-truth-distiller"
    if use_llm and vocab_rows:
        llm, model_name = LLMFactory.get_chat_model(backend=AIBackend.GEMINI, temperature=0.4)

    report = DistillGenerationReport()
    for vocab in vocab_rows:
        report.examined += 1
        user_prompt = build_distill_prompt(vocab)
        if user_prompt in existing_prompts:
            report.skipped_existing += 1
            continue

        if llm is not None:
            rewrite_prompt = LLM_DISTILL_REWRITE_PROMPT.format(
                word=vocab.word,
                cefr_level=vocab.cefr_level,
                part_of_speech=vocab.part_of_speech,
                phonetic=vocab.phonetic,
                definition_vi=vocab.definition_vi,
                definition_en=vocab.definition_en,
                example_sentence=vocab.example_sentence,
                example_translation=vocab.example_translation,
            )
            ai_message = await llm.ainvoke(
                [
                    SystemMessage(content=DISTILL_SYSTEM_PROMPT),
                    HumanMessage(content=rewrite_prompt),
                ]
            )
            assistant_reply = AIChatService._extract_text_content(ai_message.content)
        else:
            assistant_reply = build_grounded_tutor_response(vocab)

        turns_json = build_sharegpt_turns(user_prompt=user_prompt, assistant_reply=assistant_reply)
        decision = SanitizerService.evaluate_turn(
            prompt=user_prompt,
            response=assistant_reply,
            turns_json=turns_json,
        )

        chat_log = ChatLogs(
            telegram_user_id=vocab.telegram_user_id or 0,
            ai_backend=AIBackend.GEMINI.value if use_llm else "synthetic",
            model_name=model_name,
            prompt=user_prompt,
            response=decision.cleaned_response or assistant_reply,
            turns_json=decision.cleaned_turns or turns_json,
            status="verified_golden" if decision.passed else "rejected",
            rejection_reason=decision.reason,
        )
        session.add(chat_log)
        existing_prompts.add(user_prompt)

        if decision.passed:
            report.created_golden += 1
        else:
            report.rejected_by_sanitizer += 1

    await session.flush()
    return report


async def _run_cli(limit: Optional[int], cefr: Optional[str], use_llm: bool) -> None:
    """
    Open a DB session, run synthetic distillation generation, and print summary statistics.
    """
    async with get_db_session() as session:
        report = await generate_distillation_records(
            session=session,
            limit=limit,
            cefr_filter=cefr,
            use_llm=use_llm,
        )

    print(
        f"[DISTILL] examined={report.examined}, created_golden={report.created_golden}, "
        f"skipped_existing={report.skipped_existing}, rejected={report.rejected_by_sanitizer}"
    )


def main() -> None:
    """
    CLI entry point for synthetic ShareGPT distillation data generation.
    """
    parser = argparse.ArgumentParser(
        description="Convert verified vocab_ground_truth records into ShareGPT verified_golden chat_logs."
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum vocabulary rows to process.")
    parser.add_argument("--cefr", type=str, default=None, help="Optional CEFR level filter (e.g. B2, C1).")
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use Gemini Teacher LLM to vary explanations (defaults to deterministic grounded synthesis).",
    )
    args = parser.parse_args()
    asyncio.run(_run_cli(limit=args.limit, cefr=args.cefr, use_llm=args.use_llm))


if __name__ == "__main__":
    main()

