"""
name: agent_service
description: 3-Tier DB-First AI Agent Router coordinating Ground Truth lookup, Local Ollama RAG, and Teacher write-back.
"""

import html
import logging
from typing import Any, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import AIBackend, Settings, get_settings
from src.db.models import GrammarGroundTruth, VocabGroundTruth
from src.schemas.knowledge_fallback import JudgeVerdict, MissingKnowledgeBatch
from src.schemas.vocab import VocabSchema
from src.services.ai.embedding_service import EmbeddingService
from src.services.ai.llm_factory import LLMFactory
from src.services.ai.rag_retriever import KnowledgeRetriever, RetrievedItem

logger = logging.getLogger(__name__)

LOCAL_RAG_SYNTHESIS_PROMPT = (
    "You are an encouraging, articulate English tutor. Explain the user's sentence concisely in natural Vietnamese.\n"
    "Crucially, ground your explanation strictly on these verified Ground Truth lessons from our database:\n\n"
    "--- GROUND TRUTH CONTEXT ---\n"
    "{context_str}\n"
    "----------------------------\n\n"
    "Analyze the vocabulary meaning, sentence structure/grammar, and provide a clear example. "
    "Do NOT mention 'based on the context provided' or AI disclaimers."
)

TEACHER_FALLBACK_PROMPT = (
    "The user is asking about an English sentence or concept not yet found in our local database.\n"
    "Analyze this sentence: \"{user_input}\"\n\n"
    "Your tasks:\n"
    "1. Extract any new or challenging vocabulary words into 'missing_vocab'.\n"
    "2. Extract any grammar formulas, patterns, or inversions into 'missing_grammar'.\n"
    "3. Provide a clear, natural Vietnamese explanation in 'explanation'.\n"
)

CRITIC_JUDGE_PROMPT = (
    "You are a strict linguistic auditor. Review this synthesized English teaching item:\n"
    "Item: \"{item_summary}\"\n\n"
    "Check if the formula, definition, or example contains severe factual errors, hallucinations, or contradictions.\n"
    "Respond with JSON adhering to {{\"verdict\": \"pass\" | \"fail\", \"reason\": \"...\"}}."
)


class StudyAgentService:
    """Orchestrates 3-tier routing: DB Ground Truth -> Local Ollama RAG -> External Teacher Fallback."""

    def __init__(
        self,
        retriever: Optional[KnowledgeRetriever] = None,
        embedding_service: Optional[EmbeddingService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """
        Initialize StudyAgentService.

        Parameters:
            retriever (Optional[KnowledgeRetriever]): Knowledge retrieval service.
            embedding_service (Optional[EmbeddingService]): Embedding vector generator.
            settings (Optional[Settings]): Application settings override.
        """
        self._settings = settings or get_settings()
        self._embedding = embedding_service or EmbeddingService()
        self._retriever = retriever or KnowledgeRetriever(embedding_service=self._embedding, settings=self._settings)

    async def _increment_usage_count(
        self,
        session: AsyncSession,
        items: List[RetrievedItem],
    ) -> None:
        """
        Increment the usage_count metric for documents surfaced in RAG retrieval.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            items (List[RetrievedItem]): List of surfaced retrieval items.
        """
        vocab_ids = [it.id for it in items if it.kind == "vocab"]
        grammar_ids = [it.id for it in items if it.kind == "grammar"]

        if vocab_ids:
            await session.execute(
                text("UPDATE vocab_ground_truth SET usage_count = usage_count + 1 WHERE id::text = ANY(:ids)"),
                {"ids": vocab_ids},
            )
        if grammar_ids:
            await session.execute(
                text("UPDATE grammar_ground_truth SET usage_count = usage_count + 1 WHERE id::text = ANY(:ids)"),
                {"ids": grammar_ids},
            )
        await session.commit()

    async def _critic_judge_item(self, item_summary: str) -> str:
        """
        Execute LLM-as-Judge critic prompt to screen Teacher-generated knowledge.

        Parameters:
            item_summary (str): Summarized representation of the extracted item.
        Returns:
            str: 'pending_high_confidence' if verdict is pass, 'pending' otherwise.
        """
        try:
            model, _ = LLMFactory.get_chat_model(backend=AIBackend.GEMINI, temperature=0.1)
            structured_judge = model.with_structured_output(JudgeVerdict)
            verdict: JudgeVerdict = await structured_judge.ainvoke(
                CRITIC_JUDGE_PROMPT.format(item_summary=item_summary)
            )
            if verdict.verdict.strip().lower() == "pass":
                return "pending_high_confidence"
        except Exception as exc:
            logger.warning("LLM-as-Judge check failed (%s); defaulting status to 'pending'", exc)
        return "pending"

    async def _dedup_and_writeback(
        self,
        session: AsyncSession,
        fallback_batch: MissingKnowledgeBatch,
    ) -> None:
        """
        Execute 2-tier deduplication (exact pattern + semantic cosine >= 0.92) before inserting into PostgreSQL.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            fallback_batch (MissingKnowledgeBatch): Output from Teacher fallback.
        """
        target_model = self._embedding.get_model_name()

        # Ingest missing vocabulary
        for vocab in fallback_batch.missing_vocab:
            clean_word = vocab.word.strip().lower()
            # Tier 1 Dedup: exact word match
            existing = await session.execute(
                text("SELECT id FROM vocab_ground_truth WHERE lower(word) = :word LIMIT 1"),
                {"word": clean_word},
            )
            if existing.scalar_one_or_none() is not None:
                continue

            canonical_text = EmbeddingService.build_vocab_embedding_text(vocab)
            vector = await self._embedding.embed_document(canonical_text)

            # Tier 2 Dedup: cosine similarity >= 0.92
            if vector is not None:
                vec_str = "[" + ",".join(str(x) for x in vector) + "]"
                sim_res = await session.execute(
                    text("SELECT 1 - (embedding <=> CAST(:vec AS vector)) as sim FROM vocab_ground_truth WHERE embedding IS NOT NULL ORDER BY embedding <=> CAST(:vec AS vector) ASC LIMIT 1"),
                    {"vec": vec_str},
                )
                nearest_sim = sim_res.scalar_one_or_none()
                if nearest_sim is not None and float(nearest_sim) >= 0.92:
                    logger.info("Skipping vocab '%s': semantic duplicate (sim=%.3f)", clean_word, nearest_sim)
                    continue

            status = await self._critic_judge_item(f"Word: {vocab.word} | Meaning: {vocab.definition_vi}")
            record = VocabGroundTruth(
                telegram_user_id=None,
                word=vocab.word.strip(),
                phonetic=vocab.phonetic.strip(),
                part_of_speech=vocab.part_of_speech.strip(),
                definition_vi=vocab.definition_vi.strip(),
                definition_en=vocab.definition_en.strip(),
                example_sentence=vocab.example_sentence.strip(),
                example_translation=vocab.example_translation.strip(),
                cefr_level=vocab.cefr_level.strip(),
                quiz_question=vocab.quiz_question.strip(),
                quiz_options=vocab.quiz_options,
                quiz_correct_index=vocab.quiz_correct_index,
                embedding=vector,
                embedding_model=target_model,
                source="teacher_gemini",
                status=status,
                usage_count=1,
            )
            session.add(record)

        # Ingest missing grammar
        for grammar in fallback_batch.missing_grammar:
            clean_key = grammar.pattern_key.strip().lower()
            # Tier 1 Dedup: exact pattern key
            existing = await session.execute(
                text("SELECT id FROM grammar_ground_truth WHERE pattern_key = :key LIMIT 1"),
                {"key": clean_key},
            )
            if existing.scalar_one_or_none() is not None:
                continue

            canonical_text = EmbeddingService.build_grammar_embedding_text(grammar)
            vector = await self._embedding.embed_document(canonical_text)

            # Tier 2 Dedup: cosine similarity >= 0.92
            if vector is not None:
                vec_str = "[" + ",".join(str(x) for x in vector) + "]"
                sim_res = await session.execute(
                    text("SELECT 1 - (embedding <=> CAST(:vec AS vector)) as sim FROM grammar_ground_truth WHERE embedding IS NOT NULL ORDER BY embedding <=> CAST(:vec AS vector) ASC LIMIT 1"),
                    {"vec": vec_str},
                )
                nearest_sim = sim_res.scalar_one_or_none()
                if nearest_sim is not None and float(nearest_sim) >= 0.92:
                    logger.info("Skipping grammar '%s': semantic duplicate (sim=%.3f)", clean_key, nearest_sim)
                    continue

            status = await self._critic_judge_item(f"Grammar: {grammar.title} | Formula: {grammar.formula}")
            record_g = GrammarGroundTruth(
                telegram_user_id=None,
                title=grammar.title.strip(),
                pattern_key=clean_key,
                formula=grammar.formula.strip(),
                usage_vi=grammar.usage_vi.strip(),
                examples_json=[ex.model_dump() for ex in grammar.examples],
                common_mistakes_vi=grammar.common_mistakes_vi.strip(),
                cefr_level=grammar.cefr_level.strip(),
                embedding=vector,
                embedding_model=target_model,
                source="teacher_gemini",
                status=status,
                usage_count=1,
            )
            session.add(record_g)

        await session.commit()

    async def handle_study_query(
        self,
        session: AsyncSession,
        user_input: str,
    ) -> Tuple[str, str]:
        """
        Process a user learning inquiry through the 3-tier DB-first router.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            user_input (str): Incoming message from the Telegram user.
        Returns:
            Tuple[str, str]: Final response text and source tag string.
        """
        # Step 1: Search and Rerank via Hybrid RAG
        top_items, is_hit, rewritten = await self._retriever.search_and_rerank(session, user_input)

        # -------------------------------------------------------------
        # TIER 1: Direct DB Ground Truth Hit (< 50ms, 0 LLM calls)
        # -------------------------------------------------------------
        # If user queried a single word or pattern directly and top-1 match is strong (>= 0.65)
        clean_words = user_input.strip().split()
        if is_hit and len(clean_words) <= 3 and top_items and top_items[0].rerank_score >= 0.65:
            await self._increment_usage_count(session, top_items[:1])
            best = top_items[0]
            tag = "[📦 DB Ground Truth]"
            reply = f"{tag}\n\n<b>{html.escape(best.title)}</b>\n{html.escape(best.content)}"
            return reply, tag

        # -------------------------------------------------------------
        # TIER 2: Local Agent • Ollama + RAG Context (0 External API Calls)
        # -------------------------------------------------------------
        if is_hit and top_items:
            await self._increment_usage_count(session, top_items)
            tag = "[🧠 Local Agent • Ollama + RAG]"
            context_str = "\n\n".join(f"[{item.kind.upper()}]: {item.content}" for item in top_items)

            try:
                # Use local Ollama model (qwen2.5:3b)
                local_model, model_id = LLMFactory.get_chat_model(backend=AIBackend.OLLAMA, temperature=0.3)
                prompt = LOCAL_RAG_SYNTHESIS_PROMPT.format(context_str=context_str)
                ai_msg = await local_model.ainvoke(
                    [
                        SystemMessage(content=prompt),
                        HumanMessage(content=user_input),
                    ]
                )
                explanation = str(ai_msg.content).strip()
                return f"{tag}\n\n{explanation}", tag
            except Exception as exc:
                logger.warning("Local Ollama synthesis failed (%s); formatting context directly", exc)
                direct_reply = "\n\n".join(f"• <b>{html.escape(it.title)}</b>:\n{html.escape(it.content)}" for it in top_items)
                return f"{tag}\n\n{direct_reply}", tag

        # -------------------------------------------------------------
        # TIER 3: External Teacher Fallback ➔ Auto-Ingest to PostgreSQL
        # -------------------------------------------------------------
        tag = "[🌐 Teacher Fallback ➔ Đã nạp DB]"
        try:
            teacher_model, _ = LLMFactory.get_chat_model(backend=AIBackend.GEMINI, temperature=0.3)
            structured_teacher = teacher_model.with_structured_output(MissingKnowledgeBatch)
            batch: MissingKnowledgeBatch = await structured_teacher.ainvoke(
                TEACHER_FALLBACK_PROMPT.format(user_input=user_input)
            )

            # Auto-save extracted knowledge into PostgreSQL
            await self._dedup_and_writeback(session, batch)
            return f"{tag}\n\n{batch.explanation}", tag
        except Exception as exc:
            logger.exception("Teacher fallback failed: %s", exc)
            return (
                "⚠️ Hiện tại chưa có kiến thức về nội dung này trong DB và kết nối tới Teacher gặp sự cố. Bạn thử lại sau nhé!",
                "[⚠️ Error]",
            )
