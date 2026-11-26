"""
name: knowledge_fallback
description: Pydantic schemas for multi-entity teacher fallback extraction and LLM-as-Judge validation.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from src.schemas.grammar import GrammarSchema
from src.schemas.vocab import VocabSchema


class MissingKnowledgeBatch(BaseModel):
    """Container for vocabulary and grammar items extracted simultaneously from a user sentence."""

    missing_vocab: List[VocabSchema] = Field(
        default_factory=list,
        description="Any new or difficult English vocabulary items extracted from the sentence.",
    )
    missing_grammar: List[GrammarSchema] = Field(
        default_factory=list,
        description="Core grammar patterns, formulas, or sentence structures extracted from the sentence.",
    )
    explanation: str = Field(
        description="Comprehensive natural explanation in Vietnamese analyzing the sentence meaning and structure.",
    )


class JudgeVerdict(BaseModel):
    """Validation output from the LLM-as-Judge critic prompt."""

    verdict: str = Field(description="'pass' if accurate, 'fail' if erroneous or contradictory.")
    reason: str = Field(default="", description="Brief justification for the verdict.")

