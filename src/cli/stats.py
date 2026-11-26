"""
name: stats
description: Rich CLI dashboard reporting Ground Truth vocabulary health, 768-dim vector coverage, SM-2 queue, and ChatLogs pipeline counts.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from typing import Dict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ChatLogs, VocabGroundTruth
from src.db.session import get_db_session


async def collect_health_metrics(session: AsyncSession) -> Dict[str, object]:
    """
    Query PostgreSQL for vocabulary ground-truth coverage, vector dimensions, SM-2 due items, and chat log statuses.

    Parameters:
        session (AsyncSession): Active SQLAlchemy async session.

    Returns:
        Dict[str, object]: Structured dictionary of metrics for CLI display or testing.
    """
    now = datetime.now(timezone.utc)

    total_vocab = int(
        (await session.execute(select(func.count(VocabGroundTruth.id)))).scalar_one() or 0
    )
    with_embedding = int(
        (
            await session.execute(
                select(func.count(VocabGroundTruth.id)).where(
                    VocabGroundTruth.embedding.is_not(None)
                )
            )
        ).scalar_one()
        or 0
    )
    due_sm2 = int(
        (
            await session.execute(
                select(func.count(VocabGroundTruth.id)).where(
                    VocabGroundTruth.next_review_at <= now
                )
            )
        ).scalar_one()
        or 0
    )
    global_vocab = int(
        (
            await session.execute(
                select(func.count(VocabGroundTruth.id)).where(
                    VocabGroundTruth.telegram_user_id.is_(None)
                )
            )
        ).scalar_one()
        or 0
    )

    cefr_rows = (
        await session.execute(
            select(VocabGroundTruth.cefr_level, func.count(VocabGroundTruth.id))
            .group_by(VocabGroundTruth.cefr_level)
            .order_by(VocabGroundTruth.cefr_level.asc())
        )
    ).all()
    cefr_breakdown = {level: int(count) for level, count in cefr_rows}

    chat_rows = (
        await session.execute(
            select(ChatLogs.status, func.count(ChatLogs.id))
            .group_by(ChatLogs.status)
            .order_by(ChatLogs.status.asc())
        )
    ).all()
    chat_status_breakdown = {status: int(count) for status, count in chat_rows}

    return {
        "total_vocab": total_vocab,
        "with_embedding": with_embedding,
        "missing_embedding": total_vocab - with_embedding,
        "due_sm2": due_sm2,
        "global_vocab": global_vocab,
        "user_vocab": total_vocab - global_vocab,
        "cefr_breakdown": cefr_breakdown,
        "total_chat_logs": sum(chat_status_breakdown.values()),
        "chat_status_breakdown": chat_status_breakdown,
    }


def render_dashboard(metrics: Dict[str, object]) -> None:
    """
    Render collected database health metrics to the terminal using Rich tables.

    Parameters:
        metrics (Dict[str, object]): Dictionary returned by `collect_health_metrics`.
    """
    console = Console()
    console.print(Panel.fit("[bold cyan]AI-Telegram Data & Distillation Pipeline Health[/bold cyan]"))

    vocab_table = Table(title="Ground Truth Vocabulary (vocab_ground_truth)", show_header=True)
    vocab_table.add_column("Metric", style="bold")
    vocab_table.add_column("Value", justify="right", style="green")
    vocab_table.add_row("Total Words", str(metrics["total_vocab"]))
    vocab_table.add_row("With 768-dim Embedding", str(metrics["with_embedding"]))
    vocab_table.add_row("Missing Embedding", str(metrics["missing_embedding"]))
    vocab_table.add_row("Global Seed Words", str(metrics["global_vocab"]))
    vocab_table.add_row("User-Scoped Words", str(metrics["user_vocab"]))
    vocab_table.add_row("SM-2 Due Now", str(metrics["due_sm2"]))
    console.print(vocab_table)

    cefr_breakdown: Dict[str, int] = metrics["cefr_breakdown"]  # type: ignore[assignment]
    if cefr_breakdown:
        cefr_table = Table(title="CEFR Level Distribution", show_header=True)
        cefr_table.add_column("Level", style="bold")
        cefr_table.add_column("Count", justify="right")
        for level, count in cefr_breakdown.items():
            cefr_table.add_row(level, str(count))
        console.print(cefr_table)

    chat_table = Table(title="Distillation Dataset (chat_logs)", show_header=True)
    chat_table.add_column("Status", style="bold")
    chat_table.add_column("Count", justify="right", style="cyan")
    chat_status: Dict[str, int] = metrics["chat_status_breakdown"]  # type: ignore[assignment]
    chat_table.add_row("TOTAL", str(metrics["total_chat_logs"]))
    for status_name in ("raw", "verified_golden", "rejected", "exported_to_train"):
        chat_table.add_row(status_name, str(chat_status.get(status_name, 0)))
    for status_name, count in chat_status.items():
        if status_name not in {"raw", "verified_golden", "rejected", "exported_to_train"}:
            chat_table.add_row(status_name, str(count))
    console.print(chat_table)

    missing_emb = int(metrics["missing_embedding"])  # type: ignore[arg-type]
    total_logs = int(metrics["total_chat_logs"])  # type: ignore[arg-type]
    rejected_logs = int(chat_status.get("rejected", 0))
    if missing_emb > 0:
        console.print(
            f"[bold yellow]WARNING:[/bold yellow] {missing_emb} vocabulary row(s) are missing 768-dim embeddings."
        )
    if total_logs > 0 and (rejected_logs / total_logs) > 0.10:
        reject_pct = (rejected_logs / total_logs) * 100
        console.print(
            f"[bold red]WARNING:[/bold red] Chat log rejection rate is {reject_pct:.1f}% (> 10%)."
        )


async def _run() -> None:
    """
    Fetch metrics inside a database session and render the dashboard.
    """
    async with get_db_session() as session:
        metrics = await collect_health_metrics(session)
    render_dashboard(metrics)


def main() -> None:
    """
    CLI entry point for displaying Ground Truth and distillation statistics.
    """
    parser = argparse.ArgumentParser(description="Display vocabulary & distillation DB statistics.")
    parser.parse_args()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
