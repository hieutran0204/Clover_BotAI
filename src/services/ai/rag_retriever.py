"""
name: rag_retriever
description: PostgreSQL Native Hybrid RAG Retriever combining Full-Text Search (Sparse), pgvector (Dense), and Cross-Encoder Reranker.
"""

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import AIBackend, Settings, get_settings
from src.services.ai.embedding_service import EmbeddingService
from src.services.ai.llm_factory import LLMFactory

logger = logging.getLogger(__name__)

QUERY_REWRITE_PROMPT = (
    "You are an expert bilingual search optimizer for an English vocabulary and grammar learning system.\n"
    "Given the user input:\n"
    "1. If the input is about an English grammar pattern, identify the pattern and extract its formal name.\n"
    "2. Inversion structures ('Had I...', 'Were we...', 'Should you...') ALWAYS take highest priority even if the sentence ends with a question like 'what would happen?'.\n"
    "3. Wh-Cleft Sentences ONLY apply to declarative sentences starting with What (e.g. 'What we need is...'). Normal questions like 'What would happen?' or 'What should you do?' are NOT cleft sentences.\n"
    "4. If the input asks about or uses an English word, extract that exact word.\n"
    "5. If the input is a general or non-English-learning question, translate the core subject faithfully into English.\n"
    "6. STRICT RULE: NEVER output words or topics from the examples unless they are explicitly in the user's input.\n\n"
    "Grammar Pattern Guidelines:\n"
    "- 'Had I known / Had we monitored...' -> Third Conditional Inversion\n"
    "- 'Were we to adopt / Were I in your shoes...' -> Second Conditional Inversion\n"
    "- 'Should you encounter / Should any error arise...' -> First Conditional Inversion\n"
    "- 'It was the lack of... that / It is this feature that...' -> It-Cleft Sentences\n"
    "- 'What we need is... / What surprised me was...' -> Wh-Cleft Sentences\n"
    "- 'Rarely have we seen / Seldom does he...' -> Negative Inversion\n"
    "- 'The threads processing background jobs...' -> Reduced Relative Clause (Active V-ing)\n"
    "- 'The patch deployed last night...' -> Reduced Relative Clause (Passive V3/ed)\n"
    "- 'If we had designed..., we would be...' -> Mixed Conditionals\n"
    "- 'The lead recommended that every dev write...' -> Subjunctive Mood\n\n"
    "Examples:\n"
    "- 'Had we monitored the servers proactively, downtime would have been zero' -> keywords: ['Third Conditional Inversion', 'Had'], english_query: 'Third Conditional Inversion Had we monitored'\n"
    "- 'Were the team to adopt this new framework, what would happen?' -> keywords: ['Second Conditional Inversion', 'Were'], english_query: 'Second Conditional Inversion Were the team to adopt'\n"
    "- 'Should you encounter any database timeout, what should you do?' -> keywords: ['First Conditional Inversion', 'Should', 'timeout'], english_query: 'First Conditional Inversion Should you encounter'\n"
    "- 'It was the lack of indexes that caused slow latency' -> keywords: ['It-Cleft Sentences', 'indexes', 'latency'], english_query: 'It-Cleft Sentences It was that'\n"
    "- 'What we really need right now is automated testing' -> keywords: ['Wh-Cleft Sentences', 'What we need'], english_query: 'Wh-Cleft Sentences What we need is'\n"
    "- 'Rarely have we seen such zero-downtime deployment' -> keywords: ['Negative Inversion', 'Rarely'], english_query: 'Negative Inversion Rarely have we seen'\n"
    "- 'The worker threads processing background tasks' -> keywords: ['Reduced Relative Clause', 'processing'], english_query: 'Reduced Relative Clause active V-ing'\n"
    "- 'The security patch deployed last night' -> keywords: ['Reduced Relative Clause', 'deployed'], english_query: 'Reduced Relative Clause passive V3/ed'\n"
    "- 'The lead recommended that every dev write unit tests' -> keywords: ['Subjunctive Mood', 'recommend that'], english_query: 'Subjunctive Mood recommend that'\n"
    "- 'Giải thích từ vựng eloquent và cách đặt câu' -> keywords: ['eloquent', 'definition'], english_query: 'meaning and sentence example of eloquent'\n"
    "- 'Cách thay lốp xe hoặc nấu món ăn khi đi xa' -> keywords: ['car tire change', 'cooking'], english_query: 'how to change car tire or cook meal'\n\n"
    "User input: \"{user_input}\"\n\n"
    "Respond with JSON adhering to this exact schema:\n"
    "{{\n"
    "  \"keywords\": [\"keyword1\", \"keyword2\"],\n"
    "  \"english_query\": \"clean concise english search query\"\n"
    "}}"
)


class RewrittenQuery(BaseModel):
    """Structured representation of rewritten user query for bilingual RAG alignment."""

    keywords: List[str] = Field(default_factory=list, description="2 to 4 core English keywords.")
    english_query: str = Field(description="Normalized standalone English search query.")


@dataclass
class RetrievedItem:
    """Unified container for candidate records retrieved across sparse FTS and dense vector search."""

    id: str
    kind: str  # "vocab" or "grammar"
    title: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    fts_rank: float = 0.0
    dense_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0


class KnowledgeRetriever:
    """
    Executes PostgreSQL Native Hybrid Search (FTS + pgvector) and Cross-Encoder Reranking.
    """

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """
        Initialize KnowledgeRetriever with embedding service and system settings.

        Parameters:
            embedding_service (Optional[EmbeddingService]): Service used to embed search queries.
            settings (Optional[Settings]): Optional configuration override.
        """
        self._settings = settings or get_settings()
        self._embedding = embedding_service or EmbeddingService()
        self._cross_encoder = None

    def _get_cross_encoder(self) -> Any:
        """
        Lazily instantiate SentenceTransformers CrossEncoder model for candidate reranking.

        Returns:
            CrossEncoder: Initialized cross-encoder instance.
        """
        if self._cross_encoder is None:
            try:
                from sentence_transformers import CrossEncoder

                logger.info("Loading CrossEncoder model: %s", self._settings.rag_reranker_model)
                self._cross_encoder = CrossEncoder(self._settings.rag_reranker_model)
            except Exception as exc:
                logger.warning("Failed to load CrossEncoder (%s), falling back to RRF rank: %s", self._settings.rag_reranker_model, exc)
                return None
        return self._cross_encoder

    async def rewrite_query(self, user_input: str) -> RewrittenQuery:
        """
        Translate Vietnamese/mixed user input to a canonical English query and extract technical keywords.

        Parameters:
            user_input (str): Raw message from the user.
        Returns:
            RewrittenQuery: Clean English query and extracted keywords.
        """
        if not user_input.strip():
            return RewrittenQuery(keywords=[], english_query="")

        # Quick heuristic: If already pure short English phrase without Vietnamese accents, keep as-is
        has_accent = any(ord(c) > 127 for c in user_input)
        if not has_accent and len(user_input.split()) <= 4:
            clean = user_input.strip()
            return RewrittenQuery(keywords=[clean], english_query=clean)

        try:
            # Prefer local Ollama model (qwen2.5:3b) as specified by architecture v2.1
            model, _ = LLMFactory.get_chat_model(backend=AIBackend.OLLAMA, temperature=0.0)
            structured_llm = model.with_structured_output(RewrittenQuery)
            prompt = QUERY_REWRITE_PROMPT.format(user_input=user_input)
            result = await structured_llm.ainvoke(prompt)
            if isinstance(result, RewrittenQuery):
                return result
            if isinstance(result, dict):
                return RewrittenQuery.model_validate(result)
        except Exception as exc:
            logger.warning("Local Ollama query rewriting failed (%s); trying default backend", exc)
            try:
                model, _ = LLMFactory.get_chat_model(temperature=0.0)
                structured_llm = model.with_structured_output(RewrittenQuery)
                prompt = QUERY_REWRITE_PROMPT.format(user_input=user_input)
                result = await structured_llm.ainvoke(prompt)
                if isinstance(result, RewrittenQuery):
                    return result
                if isinstance(result, dict):
                    return RewrittenQuery.model_validate(result)
            except Exception as exc2:
                logger.warning("Default query rewriting failed (%s); falling back to raw input: %s", exc2, user_input)

        return RewrittenQuery(keywords=[user_input.strip()], english_query=user_input.strip())

    async def _query_sparse_fts(
        self,
        session: AsyncSession,
        search_terms: str,
        limit: int,
    ) -> List[RetrievedItem]:
        """
        Execute PostgreSQL native Full-Text Search across vocab_ground_truth and grammar_ground_truth.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            search_terms (str): Terms to match using websearch_to_tsquery.
            limit (int): Maximum sparse candidates to fetch per table.
        Returns:
            List[RetrievedItem]: Items matching sparse full-text search.
        """
        items: List[RetrievedItem] = []
        if not search_terms.strip():
            return items

        clean_words = [w.strip() for w in search_terms.split() if w.strip()]
        fts_query = " OR ".join(clean_words) if clean_words else search_terms

        # 1. Sparse Search on vocab_ground_truth
        vocab_sql = text("""
            SELECT id::text, word, definition_vi, definition_en, example_sentence, cefr_level,
                   ts_rank(to_tsvector('english', word || ' ' || COALESCE(definition_vi, '')), websearch_to_tsquery('english', :query)) as rank
            FROM vocab_ground_truth
            WHERE status NOT IN ('quarantined', 'rejected')
              AND to_tsvector('english', word || ' ' || COALESCE(definition_vi, '')) @@ websearch_to_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT :limit
        """)
        vocab_res = await session.execute(vocab_sql, {"query": fts_query, "limit": limit})
        for row in vocab_res.mappings():
            content = f"{row['word']} ({row['cefr_level']}): {row['definition_en']} | {row['definition_vi']} | Example: {row['example_sentence']}"
            items.append(
                RetrievedItem(
                    id=row["id"],
                    kind="vocab",
                    title=row["word"],
                    content=content,
                    metadata={"definition_vi": row["definition_vi"], "cefr_level": row["cefr_level"]},
                    fts_rank=float(row["rank"]),
                )
            )

        # 2. Sparse Search on grammar_ground_truth
        grammar_sql = text("""
            SELECT id::text, title, pattern_key, formula, usage_vi, cefr_level,
                   ts_rank(to_tsvector('english', title || ' ' || formula || ' ' || usage_vi), websearch_to_tsquery('english', :query)) as rank
            FROM grammar_ground_truth
            WHERE status NOT IN ('quarantined', 'rejected')
              AND to_tsvector('english', title || ' ' || formula || ' ' || usage_vi) @@ websearch_to_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT :limit
        """)
        grammar_res = await session.execute(grammar_sql, {"query": fts_query, "limit": limit})
        for row in grammar_res.mappings():
            content = f"{row['title']} ({row['cefr_level']}): Formula: {row['formula']} | Usage: {row['usage_vi']}"
            items.append(
                RetrievedItem(
                    id=row["id"],
                    kind="grammar",
                    title=row["title"],
                    content=content,
                    metadata={"pattern_key": row["pattern_key"], "formula": row["formula"], "cefr_level": row["cefr_level"]},
                    fts_rank=float(row["rank"]),
                )
            )

        return items

    async def _query_dense_vector(
        self,
        session: AsyncSession,
        query_vector: List[float],
        limit: int,
    ) -> List[RetrievedItem]:
        """
        Execute pgvector Cosine Distance search across vocab and grammar ground truth tables.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            query_vector (List[float]): 768-dimensional query vector.
            limit (int): Maximum dense candidates to fetch per table.
        Returns:
            List[RetrievedItem]: Items matching dense cosine similarity search.
        """
        items: List[RetrievedItem] = []
        vec_literal = "[" + ",".join(str(x) for x in query_vector) + "]"

        # 1. Dense search on vocab_ground_truth
        vocab_sql = text("""
            SELECT id::text, word, definition_vi, definition_en, example_sentence, cefr_level,
                   1 - (embedding <=> CAST(:vec AS vector)) as cosine_sim
            FROM vocab_ground_truth
            WHERE status NOT IN ('quarantined', 'rejected')
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vec AS vector) ASC
            LIMIT :limit
        """)
        vocab_res = await session.execute(vocab_sql, {"vec": vec_literal, "limit": limit})
        for row in vocab_res.mappings():
            content = f"{row['word']} ({row['cefr_level']}): {row['definition_en']} | {row['definition_vi']} | Example: {row['example_sentence']}"
            items.append(
                RetrievedItem(
                    id=row["id"],
                    kind="vocab",
                    title=row["word"],
                    content=content,
                    metadata={"definition_vi": row["definition_vi"], "cefr_level": row["cefr_level"]},
                    dense_score=float(row["cosine_sim"]),
                )
            )

        # 2. Dense search on grammar_ground_truth
        grammar_sql = text("""
            SELECT id::text, title, pattern_key, formula, usage_vi, cefr_level,
                   1 - (embedding <=> CAST(:vec AS vector)) as cosine_sim
            FROM grammar_ground_truth
            WHERE status NOT IN ('quarantined', 'rejected')
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vec AS vector) ASC
            LIMIT :limit
        """)
        grammar_res = await session.execute(grammar_sql, {"vec": vec_literal, "limit": limit})
        for row in grammar_res.mappings():
            content = f"{row['title']} ({row['cefr_level']}): Formula: {row['formula']} | Usage: {row['usage_vi']}"
            items.append(
                RetrievedItem(
                    id=row["id"],
                    kind="grammar",
                    title=row["title"],
                    content=content,
                    metadata={"pattern_key": row["pattern_key"], "formula": row["formula"], "cefr_level": row["cefr_level"]},
                    dense_score=float(row["cosine_sim"]),
                )
            )

        return items

    @staticmethod
    def _apply_rrf(
        sparse_items: List[RetrievedItem],
        dense_items: List[RetrievedItem],
        k_constant: int = 60,
    ) -> List[RetrievedItem]:
        """
        Merge sparse and dense retrieval rankings using Reciprocal Rank Fusion (RRF).

        Parameters:
            sparse_items (List[RetrievedItem]): Items ordered by sparse FTS rank.
            dense_items (List[RetrievedItem]): Items ordered by dense cosine similarity.
            k_constant (int): Smoothing constant (standard default is 60).
        Returns:
            List[RetrievedItem]: Deduplicated candidates sorted by RRF score descending.
        """
        fused: Dict[str, RetrievedItem] = {}

        # Accumulate sparse ranks
        for rank, item in enumerate(sparse_items, start=1):
            if item.id not in fused:
                fused[item.id] = item
            fused[item.id].fts_rank = item.fts_rank
            fused[item.id].rrf_score += 0.5 / (k_constant + rank)

        # Accumulate dense ranks
        for rank, item in enumerate(dense_items, start=1):
            if item.id not in fused:
                fused[item.id] = item
            fused[item.id].dense_score = item.dense_score
            fused[item.id].rrf_score += 0.5 / (k_constant + rank)

        # Sort descending by reciprocal rank fusion score
        sorted_items = sorted(fused.values(), key=lambda x: x.rrf_score, reverse=True)
        return sorted_items

    async def search_and_rerank(
        self,
        session: AsyncSession,
        user_input: str,
    ) -> Tuple[List[RetrievedItem], bool, RewrittenQuery]:
        """
        Execute the complete 5-step RAG pipeline:
        1. Query rewriting (bilingual normalization)
        2. Sparse FTS retrieval (PostgreSQL tsvector)
        3. Dense vector retrieval (nomic-embed-text)
        4. Reciprocal Rank Fusion (Top-15 candidates)
        5. Cross-Encoder Reranking (Top-3 items + Threshold Gate)

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            user_input (str): Incoming message from the user.
        Returns:
            Tuple[List[RetrievedItem], bool, RewrittenQuery]:
                Top reranked items (up to rag_top_k), is_hit boolean, and RewrittenQuery metadata.
        """
        # Step 1: Query Rewriting
        rewritten = await self.rewrite_query(user_input)
        search_query = rewritten.english_query or user_input.strip()

        # Step 2: Dense Query Embedding
        query_vector = await self._embedding.embed_query(search_query)

        # Step 3: Sparse Search (combine keywords + search query)
        sparse_terms = " ".join(rewritten.keywords) if rewritten.keywords else search_query
        sparse_items = await self._query_sparse_fts(
            session=session,
            search_terms=sparse_terms,
            limit=self._settings.rag_candidate_k,
        )

        # Dense Search
        dense_items: List[RetrievedItem] = []
        if query_vector is not None:
            dense_items = await self._query_dense_vector(
                session=session,
                query_vector=query_vector,
                limit=self._settings.rag_candidate_k,
            )

        # Step 4: Reciprocal Rank Fusion (take top RAG_CANDIDATE_K)
        candidates = self._apply_rrf(sparse_items, dense_items)[: self._settings.rag_candidate_k]
        if not candidates:
            return [], False, rewritten

        # Step 5: Cross-Encoder Reranker
        cross_encoder = self._get_cross_encoder()
        if cross_encoder is not None:
            pairs = []
            for item in candidates:
                if item.kind == "vocab" and item.title and (
                    item.title.lower() in user_input.lower() or item.title.lower() in search_query.lower()
                ):
                    pair_query = f"vocabulary word {item.title} definition in context: {search_query}"
                else:
                    pair_query = search_query
                pairs.append((pair_query, item.content))
            try:
                scores = cross_encoder.predict(pairs)
                for item, score in zip(candidates, scores):
                    # Normalize raw CrossEncoder logits to [0.0, 1.0] probability via Sigmoid
                    val = float(score)
                    item.rerank_score = 1.0 / (1.0 + math.exp(-val))
                candidates.sort(key=lambda x: x.rerank_score, reverse=True)
            except Exception as exc:
                logger.warning("Reranking failed (%s); retaining RRF ordering", exc)

        # Select Top-K
        top_k_items = candidates[: self._settings.rag_top_k]
        top1_score = top_k_items[0].rerank_score if cross_encoder is not None else top_k_items[0].rrf_score
        is_hit = top1_score >= self._settings.rag_reranker_threshold

        return top_k_items, is_hit, rewritten
