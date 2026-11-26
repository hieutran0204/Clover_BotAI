"""
name: sm2
description: Pure implementation of the SuperMemo-2 (SM-2) spaced repetition scheduling algorithm.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass(frozen=True)
class SM2Result:
    """Computed spaced repetition state after a review attempt."""

    repetition_count: int
    ease_factor: float
    interval_days: int
    next_review_at: datetime


def calculate_sm2(
    repetition_count: int,
    ease_factor: float,
    interval_days: int,
    quality: int,
    now: Optional[datetime] = None,
) -> SM2Result:
    """
    Calculate updated SM-2 parameters and next review timestamp from a 0-5 recall quality score.

    Parameters:
        repetition_count (int): Number of consecutive successful reviews before this attempt.
        ease_factor (float): Current ease factor (typically initialized at 2.5, floor 1.3).
        interval_days (int): Previous scheduled interval in days.
        quality (int): Recall quality rating from 0 (complete blackout) to 5 (perfect recall).
        now (Optional[datetime]): Reference UTC timestamp; defaults to current UTC time.
    Returns:
        SM2Result: Updated repetition_count, ease_factor, interval_days, and next_review_at.
    """
    clamped_q = max(0, min(5, int(quality)))
    ref_now = now or datetime.now(timezone.utc)

    if clamped_q >= 3:
        if repetition_count == 0:
            new_interval = 1
        elif repetition_count == 1:
            new_interval = 6
        else:
            new_interval = max(1, round(interval_days * ease_factor))
        new_repetition = repetition_count + 1
    else:
        new_repetition = 0
        new_interval = 1

    # Classic SM-2 ease factor update formula with 1.3 lower bound
    delta = 0.1 - (5 - clamped_q) * (0.08 + (5 - clamped_q) * 0.02)
    new_ease_factor = max(1.3, round(ease_factor + delta, 4))
    next_review_at = ref_now + timedelta(days=new_interval)

    return SM2Result(
        repetition_count=new_repetition,
        ease_factor=new_ease_factor,
        interval_days=new_interval,
        next_review_at=next_review_at,
    )

