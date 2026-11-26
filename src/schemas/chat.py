"""
name: chat
description: Pydantic schemas representing ShareGPT-compatible multi-turn conversation logs.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    """Single conversational turn formatted for ShareGPT knowledge distillation export."""

    sender: Literal["human", "gpt", "system"] = Field(alias="from")
    value: str = Field(description="Text content of the message turn")

    model_config = {"populate_by_name": True}

