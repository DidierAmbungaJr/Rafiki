from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Emotion = Literal["neutral", "happy", "sad", "surprised", "thinking"]
Movement = Literal[
    "none",
    "swing",
    "dance",
    "walk_forward",
    "walk_backward",
    "turn_left",
    "turn_right",
    "stop",
]
ScreenMode = Literal["face", "text", "learning", "quiz"]


class RafikiDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speech: str = Field(max_length=180)
    emotion: Emotion = "neutral"
    movement: Movement = "none"
    screen_mode: ScreenMode = "face"
    screen_content: str = Field(default="", max_length=160)
