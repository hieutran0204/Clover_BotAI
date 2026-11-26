"""
name: test_sm2
description: Unit tests for the SuperMemo-2 spaced repetition algorithm.
"""

from datetime import datetime, timedelta, timezone

from src.algorithms.sm2 import calculate_sm2


def test_sm2_progression_on_correct_recalls() -> None:
    """Verify interval progression (1 -> 6 -> round(6 * EF)) across consecutive successful recalls."""
    t0 = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)

    r1 = calculate_sm2(repetition_count=0, ease_factor=2.5, interval_days=1, quality=4, now=t0)
    assert r1.repetition_count == 1
    assert r1.interval_days == 1
    assert r1.ease_factor == 2.5
    assert r1.next_review_at == t0 + timedelta(days=1)

    r2 = calculate_sm2(
        repetition_count=r1.repetition_count,
        ease_factor=r1.ease_factor,
        interval_days=r1.interval_days,
        quality=5,
        now=t0,
    )
    assert r2.repetition_count == 2
    assert r2.interval_days == 6
    assert r2.ease_factor == 2.6

    r3 = calculate_sm2(
        repetition_count=r2.repetition_count,
        ease_factor=r2.ease_factor,
        interval_days=r2.interval_days,
        quality=4,
        now=t0,
    )
    assert r3.repetition_count == 3
    assert r3.interval_days == round(6 * 2.6)


def test_sm2_resets_repetition_and_respects_ease_floor_on_failure() -> None:
    """Verify failed recall (quality < 3) resets repetition_count and clamps ease_factor >= 1.3."""
    t0 = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)

    res = calculate_sm2(repetition_count=5, ease_factor=1.35, interval_days=30, quality=0, now=t0)
    assert res.repetition_count == 0
    assert res.interval_days == 1
    assert res.ease_factor == 1.3
    assert res.next_review_at == t0 + timedelta(days=1)

