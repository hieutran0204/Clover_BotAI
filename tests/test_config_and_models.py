"""
name: test_config_and_models
description: Unit tests for Pydantic Settings, VocabSchema validation, and SQLAlchemy ORM definitions.
"""

import pytest
from pydantic import ValidationError

from src.core.config import AIBackend, Settings
from src.db.models import ChatLogs, QuizLogs, VocabGroundTruth
from src.schemas.vocab import VocabSchema


def test_settings_admin_ids_parsing() -> None:
    """Verify comma-separated ADMIN_USER_IDS string parses into a list of integers."""
    settings = Settings(admin_user_ids="111, 222, 333", _env_file=None)
    assert settings.admin_user_ids == [111, 222, 333]
    assert settings.ai_backend == AIBackend.OLLAMA
    assert settings.data_dir == "./data"


def test_vocab_schema_validation_valid() -> None:
    """Verify VocabSchema accepts valid structured vocabulary lesson data."""
    vocab = VocabSchema(
        word="resilient",
        phonetic="/rɪˈzɪl.jənt/",
        part_of_speech="adjective",
        definition_vi="kiên cường, mau phục hồi",
        definition_en="able to recover quickly from difficulties",
        example_sentence="She remained resilient despite many setbacks.",
        example_translation="Cô ấy vẫn kiên cường dù gặp nhiều trở ngại.",
        cefr_level="B2",
        quiz_question="What does 'resilient' mean?",
        quiz_options=["fragile", "able to recover quickly", "exhausted", "careless"],
        quiz_correct_index=1,
    )
    assert vocab.word == "resilient"
    assert len(vocab.quiz_options) == 4
    assert vocab.quiz_correct_index == 1


def test_vocab_schema_rejects_blank_option() -> None:
    """Verify VocabSchema raises ValidationError when an option is empty."""
    with pytest.raises(ValidationError):
        VocabSchema(
            word="ephemeral",
            phonetic="/ɪˈfem.ər.əl/",
            part_of_speech="adjective",
            definition_vi="ngắn ngủi",
            definition_en="lasting for a very short time",
            example_sentence="Fame can be ephemeral.",
            example_translation="Danh vọng có thể chỉ là thoáng qua.",
            cefr_level="C1",
            quiz_question="Choose the synonym of ephemeral:",
            quiz_options=["short-lived", "   ", "permanent", "ancient"],
            quiz_correct_index=0,
        )


def test_orm_models_metadata_registered() -> None:
    """Verify all Phase 1 tables are registered on SQLAlchemy metadata."""
    assert VocabGroundTruth.__tablename__ == "vocab_ground_truth"
    assert ChatLogs.__tablename__ == "chat_logs"
    assert QuizLogs.__tablename__ == "quiz_logs"

