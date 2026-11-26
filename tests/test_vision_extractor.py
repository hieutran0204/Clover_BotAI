"""
name: test_vision_extractor
description: Unit tests for VisionExtractorService multimodal image OCR and chunked PDF extraction.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.schemas.vocab import VocabBatchSchema, VocabSchema
from src.services.ai import vision_extractor
from src.services.ai.vision_extractor import VisionExtractorService


def _make_vocab(word: str) -> VocabSchema:
    """
    Build a minimal VocabSchema item for OCR and PDF unit tests.
    """
    return VocabSchema(
        word=word,
        phonetic="/test/",
        part_of_speech="noun",
        definition_vi="nghĩa",
        definition_en="meaning",
        example_sentence=f"Sentence with {word}.",
        example_translation="Câu ví dụ.",
        cefr_level="B2",
        quiz_question=f"What is {word}?",
        quiz_options=["A", "B", "C", "D"],
        quiz_correct_index=0,
    )


@pytest.mark.asyncio
async def test_extract_from_image_builds_base64_multimodal_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify image bytes are base64-encoded into a data URI and deduplicated after extraction.
    """
    fake_structured_llm = MagicMock()
    fake_structured_llm.ainvoke = AsyncMock(
        return_value=VocabBatchSchema(items=[_make_vocab("latency"), _make_vocab("Latency")])
    )
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured_llm
    monkeypatch.setattr(
        vision_extractor.LLMFactory,
        "get_chat_model",
        MagicMock(return_value=(fake_llm, "gemini-3.8-flash")),
    )

    service = VisionExtractorService()
    raw_bytes = b"fake-jpeg-payload"
    items = await service.extract_from_image(raw_bytes, mime_type="image/jpeg", caption="notes")

    assert [item.word for item in items] == ["latency"]
    sent_messages = fake_structured_llm.ainvoke.await_args.args[0]
    human_content = sent_messages[1].content
    expected_b64 = base64.b64encode(raw_bytes).decode("ascii")
    assert human_content[1]["image_url"]["url"] == f"data:image/jpeg;base64,{expected_b64}"
    assert "notes" in human_content[0]["text"]


def test_extract_text_chunks_from_pdf_caps_at_max_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure PDFs longer than 15 pages are capped into 3-page chunks and flagged as truncated.
    """
    pages = [SimpleNamespace(extract_text=lambda i=idx: f"Vocab page {i + 1}") for idx in range(20)]
    monkeypatch.setattr(vision_extractor, "PdfReader", MagicMock(return_value=SimpleNamespace(pages=pages)))

    service = VisionExtractorService(pages_per_chunk=3, max_pdf_pages=15)
    chunks, total_pages, was_truncated = service.extract_text_chunks_from_pdf(b"%PDF-1.4 dummy")

    assert total_pages == 20
    assert was_truncated is True
    assert len(chunks) == 5
    assert "[Page 1]" in chunks[0]
    assert "[Page 15]" in chunks[-1]
    assert "[Page 16]" not in chunks[-1]


def test_extract_text_chunks_from_scanned_pdf_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Ensure PDFs with zero selectable text raise ValueError instead of making wasted LLM calls.
    """
    pages = [SimpleNamespace(extract_text=lambda: "   ") for _ in range(3)]
    monkeypatch.setattr(vision_extractor, "PdfReader", MagicMock(return_value=SimpleNamespace(pages=pages)))

    service = VisionExtractorService()
    with pytest.raises(ValueError, match="No selectable text"):
        service.extract_text_chunks_from_pdf(b"%PDF-1.4 scanned")

