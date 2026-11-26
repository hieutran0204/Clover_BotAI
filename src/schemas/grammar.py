"""
name: grammar
description: Pydantic validation schemas for English grammar patterns, formulas, and structured teacher responses.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class GrammarExampleSchema(BaseModel):
    """Represents a sample sentence illustrating a grammar structure with Vietnamese translation."""

    sentence: str = Field(description="Natural English sentence illustrating the target grammar pattern.")
    translation: str = Field(description="Accurate Vietnamese translation of the example sentence.")


class GrammarSchema(BaseModel):
    """Represents a complete structured English grammar lesson and formula."""

    title: str = Field(description="Human-readable title (e.g. 'Third Conditional Inversion', 'Cleft Sentence').")
    pattern_key: str = Field(description="Normalized snake_case or canonical pattern identifier for deduplication.")
    formula: str = Field(description="Grammar formula (e.g. 'Had + S + V3/ed, S + would have + V3/ed').")
    usage_vi: str = Field(description="Detailed explanation of when and how to use this grammar rule in Vietnamese.")
    examples: List[GrammarExampleSchema] = Field(
        min_length=1,
        description="List of at least one example sentence with translation.",
    )
    common_mistakes_vi: str = Field(
        default="",
        description="Common pitfalls or errors Vietnamese learners frequently make with this pattern.",
    )
    cefr_level: str = Field(
        default="B1",
        description="CEFR target proficiency level (A1, A2, B1, B2, C1, C2).",
    )


class GrammarBatchSchema(BaseModel):
    """Batch container for multi-item structured grammar generation."""

    items: List[GrammarSchema] = Field(
        default_factory=list,
        description="List of structured grammar items.",
    )

