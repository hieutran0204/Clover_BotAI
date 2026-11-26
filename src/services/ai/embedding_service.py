"""
name: embedding_service
description: Generates 768-dimensional vector embeddings via Ollama (nomic-embed-text) or Gemini matching pgvector schema.
"""

import logging
from typing import Any, List, Optional

from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_ollama import OllamaEmbeddings

from src.core.config import EmbeddingProvider, Settings, get_settings
from src.schemas.grammar import GrammarSchema
from src.schemas.vocab import VocabSchema

logger = logging.getLogger(__name__)


class NomicEmbeddingsWrapper(Embeddings):
    """
    Wraps an underlying LangChain Embeddings instance to enforce Nomic's prefix convention.

    Documents indexed into the database receive 'search_document: ', while incoming user
    search queries receive 'search_query: '.
    """

    def __init__(self, base_embeddings: Embeddings) -> None:
        """
        Initialize the wrapper with a base embeddings provider.

        Parameters:
            base_embeddings (Embeddings): Underlying embedder instance (e.g. OllamaEmbeddings).
        """
        self.embeddings = base_embeddings

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed search documents with the required 'search_document: ' prefix.

        Parameters:
            texts (List[str]): List of document strings to index.
        Returns:
            List[List[float]]: List of embedding vectors.
        """
        prefixed = [f"search_document: {t}" for t in texts]
        return self.embeddings.embed_documents(prefixed)

    def embed_query(self, text: str) -> List[float]:
        """
        Embed a search query with the required 'search_query: ' prefix.

        Parameters:
            text (str): Raw user search query string.
        Returns:
            List[float]: Single query embedding vector.
        """
        return self.embeddings.embed_query(f"search_query: {text}")

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Asynchronously embed search documents with the 'search_document: ' prefix.

        Parameters:
            texts (List[str]): List of document strings to index.
        Returns:
            List[List[float]]: List of embedding vectors.
        """
        prefixed = [f"search_document: {t}" for t in texts]
        return await self.embeddings.aembed_documents(prefixed)

    async def aembed_query(self, text: str) -> List[float]:
        """
        Asynchronously embed a search query with the 'search_query: ' prefix.

        Parameters:
            text (str): Raw user search query string.
        Returns:
            List[float]: Single query embedding vector.
        """
        return await self.embeddings.aembed_query(f"search_query: {text}")


class EmbeddingService:
    """Computes fixed-dimension vector embeddings for vocabulary, grammar, and hybrid RAG queries."""

    def __init__(
        self,
        embedder: Optional[Any] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """
        Initialize EmbeddingService with an optional injected embedder for deterministic testing.

        Parameters:
            embedder (Optional[Any]): Optional LangChain embeddings object.
            settings (Optional[Settings]): Optional configuration override.
        """
        self._settings = settings or get_settings()
        self._embedder = embedder

    def get_model_name(self) -> str:
        """
        Return the canonical model name identifier for tracking embedding provenance.

        Returns:
            str: Identifier such as 'nomic-embed-text' or 'gemini-embedding-001'.
        """
        if self._settings.embedding_provider == EmbeddingProvider.OLLAMA:
            return self._settings.ollama_embedding_model
        return self._settings.gemini_embedding_model

    def _get_embedder(self) -> Optional[Any]:
        """
        Lazily instantiate the configured embedding client (Ollama nomic-embed-text or Gemini).

        Returns:
            Optional[Any]: Configured Embeddings instance or None if unconfigured.
        """
        if self._embedder is not None:
            return self._embedder

        if self._settings.embedding_provider == EmbeddingProvider.OLLAMA:
            base_ollama = OllamaEmbeddings(
                model=self._settings.ollama_embedding_model,
                base_url=self._settings.resolved_ollama_base_url,
            )
            self._embedder = NomicEmbeddingsWrapper(base_ollama)
            return self._embedder

        if not self._settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY not set; skipping vector embedding generation.")
            return None

        self._embedder = GoogleGenerativeAIEmbeddings(
            model=self._settings.gemini_embedding_model,
            google_api_key=self._settings.gemini_api_key,
        )
        return self._embedder

    @staticmethod
    def build_vocab_embedding_text(vocab: VocabSchema) -> str:
        """
        Build a canonical text representation of a vocabulary entry for semantic embedding.

        Parameters:
            vocab (VocabSchema): Structured vocabulary entry.
        Returns:
            str: Canonical string combining word, definitions, and example sentence.
        """
        return (
            f"{vocab.word} ({vocab.part_of_speech}, {vocab.cefr_level}): "
            f"{vocab.definition_en} | {vocab.definition_vi} | Example: {vocab.example_sentence}"
        )

    @staticmethod
    def build_grammar_embedding_text(grammar: GrammarSchema) -> str:
        """
        Build a canonical text representation of a grammar pattern for semantic embedding.

        Parameters:
            grammar (GrammarSchema): Structured grammar entry.
        Returns:
            str: Canonical string combining pattern title, formula, usage, and primary example.
        """
        sample_sentence = grammar.examples[0].sentence if grammar.examples else ""
        return (
            f"{grammar.title} ({grammar.cefr_level}): Formula: {grammar.formula} | "
            f"Usage: {grammar.usage_vi} | Example: {sample_sentence}"
        )

    async def embed_query(self, query: str) -> Optional[List[float]]:
        """
        Compute an embedding vector specifically optimized for user search queries.

        Parameters:
            query (str): Input query text.
        Returns:
            Optional[List[float]]: 768-dimensional float vector or None if unavailable.
        """
        embedder = self._get_embedder()
        if embedder is None or not query.strip():
            return None
        vector = await embedder.aembed_query(query)
        return [float(x) for x in vector]

    async def embed_document(self, text: str) -> Optional[List[float]]:
        """
        Compute a single document vector embedding matching the configured pgvector dimensions.

        Parameters:
            text (str): Document text to embed for database indexing.
        Returns:
            Optional[List[float]]: 768-dimensional float vector or None if unavailable.
        """
        embedder = self._get_embedder()
        if embedder is None or not text.strip():
            return None
        vectors = await embedder.aembed_documents([text])
        if not vectors:
            return None
        return [float(x) for x in vectors[0]]

    async def embed_text(self, text: str) -> Optional[List[float]]:
        """
        Backward-compatible document embedding alias for single text strings.

        Parameters:
            text (str): Document text string to embed.
        Returns:
            Optional[List[float]]: Embedding float vector of length 768, or None.
        """
        return await self.embed_document(text)

    async def embed_texts(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Compute batch vector embeddings for a list of document strings.

        Parameters:
            texts (List[str]): List of document texts for database indexing.
        Returns:
            List[Optional[List[float]]]: List of embedding vectors aligned 1:1 with input texts.
        """
        if not texts:
            return []
        embedder = self._get_embedder()
        if embedder is None:
            return [None for _ in texts]
        vectors = await embedder.aembed_documents(texts)
        return [[float(x) for x in vec] for vec in vectors]
