"""
name: vision_extractor
description: Multimodal OCR and chunked PDF extraction service converting images and PDFs into VocabSchema batches.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from pypdf import PdfReader

from src.core.config import AIBackend
from src.schemas.vocab import VocabBatchSchema, VocabSchema
from src.services.ai.llm_factory import LLMFactory
from src.services.vocab_ingestion_service import VocabIngestionService

logger = logging.getLogger(__name__)

IMAGE_OCR_PROMPT = """Inspect this image of English study material, notes, book page, or vocabulary list.
Read all visible English text carefully and extract up to 12 distinct, high-value vocabulary words or idioms worth studying (prioritize B1-C2 words or terms highlighted/listed in the material).

Rules:
- Focus strictly on words/phrases clearly present in the image.
- Normalize each word to clean lowercase singular/base form.
- For every item, generate complete fields: phonetic IPA, part_of_speech, Vietnamese definition (definition_vi), concise English definition (definition_en), natural example_sentence + Vietnamese translation, CEFR level (A1-C2), and a 4-option multiple choice quiz (quiz_options length 4, quiz_correct_index 0..3).
- If no readable English vocabulary is found, return items=[].
{caption_hint}"""

PDF_CHUNK_PROMPT = """Analyze this excerpt from an English study PDF and extract up to 8 high-value vocabulary words or idioms (prioritize CEFR B1-C2, domain terms, or key vocabulary).

Rules:
- Focus only on vocabulary actually appearing in the excerpt below.
- Normalize each word to lowercase singular/base form.
- Return complete VocabSchema items with phonetic IPA, part_of_speech, definition_vi, definition_en, example_sentence, example_translation, cefr_level, and a 4-option multiple-choice quiz.
- If the excerpt contains no useful vocabulary (e.g., cover page or table of contents only), return items=[].
{caption_hint}

Excerpt:
{chunk_text}"""


class VisionExtractorService:
    """
    Extract structured English vocabulary from images (Gemini Vision) and PDF documents (chunked pypdf).
    """

    def __init__(
        self,
        pages_per_chunk: int = 3,
        max_pdf_pages: int = 15,
    ) -> None:
        """
        Configure chunking and page limits for multimodal document ingestion.

        Parameters:
            pages_per_chunk (int): Number of PDF pages bundled into each LLM prompt.
            max_pdf_pages (int): Upper page cap processed per PDF to protect memory and latency.
        """
        self.pages_per_chunk = pages_per_chunk
        self.max_pdf_pages = max_pdf_pages

    async def extract_from_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        caption: Optional[str] = None,
    ) -> List[VocabSchema]:
        """
        Extract structured vocabulary items from raw image bytes using Gemini multimodal vision.

        Parameters:
            image_bytes (bytes): Encoded image bytes (JPEG/PNG/WEBP).
            mime_type (str): Image MIME type for the base64 data URI.
            caption (Optional[str]): Optional Telegram caption guiding what the user wants extracted.

        Returns:
            List[VocabSchema]: Deduplicated list of extracted vocabulary entries.
        """
        if not image_bytes:
            raise ValueError("Image payload is empty.")

        llm, _ = LLMFactory.get_chat_model(backend=AIBackend.GEMINI, temperature=0.2)
        structured_llm = llm.with_structured_output(VocabBatchSchema)

        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        caption_hint = f"\nUser note/context: {caption.strip()}" if caption and caption.strip() else ""
        prompt = IMAGE_OCR_PROMPT.format(caption_hint=caption_hint)

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
                },
            ]
        )

        result = await structured_llm.ainvoke(
            [
                SystemMessage(
                    content="You are an expert OCR and English curriculum extraction assistant."
                ),
                message,
            ]
        )
        batch = (
            result
            if isinstance(result, VocabBatchSchema)
            else VocabBatchSchema.model_validate(result)
        )
        return self._deduplicate_batch(batch.items)

    def extract_text_chunks_from_pdf(
        self,
        pdf_bytes: bytes,
    ) -> Tuple[List[str], int, bool]:
        """
        Read a PDF in memory and split extracted page text into bounded multi-page chunks.

        Parameters:
            pdf_bytes (bytes): Raw PDF file contents.

        Returns:
            Tuple[List[str], int, bool]: `(chunks, total_pages, was_truncated)`.

        Raises:
            ValueError: If the PDF contains no selectable text across the inspected pages.
        """
        reader = PdfReader(io.BytesIO(pdf_bytes))
        total_pages = len(reader.pages)
        capped_pages = min(total_pages, self.max_pdf_pages)
        was_truncated = total_pages > self.max_pdf_pages

        page_texts: List[str] = []
        for idx in range(capped_pages):
            text = (reader.pages[idx].extract_text() or "").strip()
            if text:
                page_texts.append(f"[Page {idx + 1}]\n{text}")

        if not page_texts:
            raise ValueError(
                "No selectable text could be extracted from the PDF (it may be a scanned image PDF)."
            )

        chunks: List[str] = []
        for start in range(0, len(page_texts), self.pages_per_chunk):
            chunk = "\n\n".join(page_texts[start : start + self.pages_per_chunk])
            chunks.append(chunk[:12000])

        return chunks, total_pages, was_truncated

    async def extract_from_pdf(
        self,
        pdf_bytes: bytes,
        caption: Optional[str] = None,
        backend: AIBackend = AIBackend.GEMINI,
    ) -> Tuple[List[VocabSchema], int, bool]:
        """
        Extract structured vocabulary across chunked PDF pages while capping token growth.

        Parameters:
            pdf_bytes (bytes): Raw PDF bytes downloaded from Telegram.
            caption (Optional[str]): Optional user caption describing extraction goals.
            backend (AIBackend): AI backend used to extract structured items per chunk.

        Returns:
            Tuple[List[VocabSchema], int, bool]: `(unique_items, total_pages, was_truncated)`.
        """
        chunks, total_pages, was_truncated = self.extract_text_chunks_from_pdf(pdf_bytes)

        llm, _ = LLMFactory.get_chat_model(backend=backend, temperature=0.2)
        structured_llm = llm.with_structured_output(VocabBatchSchema)
        caption_hint = f"\nUser note/context: {caption.strip()}" if caption and caption.strip() else ""

        collected: List[VocabSchema] = []
        for chunk in chunks:
            prompt = PDF_CHUNK_PROMPT.format(caption_hint=caption_hint, chunk_text=chunk)
            result = await structured_llm.ainvoke(
                [
                    SystemMessage(
                        content="You are an expert English vocabulary analyst processing study documents."
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            batch = (
                result
                if isinstance(result, VocabBatchSchema)
                else VocabBatchSchema.model_validate(result)
            )
            collected.extend(batch.items)

        return self._deduplicate_batch(collected), total_pages, was_truncated

    @staticmethod
    def _deduplicate_batch(items: List[VocabSchema]) -> List[VocabSchema]:
        """
        Remove case-insensitive duplicate words while preserving extraction order.

        Parameters:
            items (List[VocabSchema]): Raw extracted vocabulary entries.

        Returns:
            List[VocabSchema]: Unique vocabulary entries normalized by lowercase word.
        """
        seen: set[str] = set()
        unique: List[VocabSchema] = []
        for item in items:
            norm = VocabIngestionService.normalize_word(item.word)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            unique.append(item)
        return unique

