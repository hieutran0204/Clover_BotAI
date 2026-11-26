"""
name: admin_review
description: CLI tool for human-in-the-loop audit and approval of quarantined or pending knowledge records.
"""

import argparse
import asyncio
import logging
from typing import Optional
import uuid

from rich.console import Console
from rich.table import Table
from sqlalchemy import select, update

from src.db.models import GrammarGroundTruth, VocabGroundTruth
from src.db.session import get_db_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()


async def list_records(target_status: str = "quarantined") -> None:
    """
    Display a Rich table of records matching the given status across vocab and grammar tables.

    Parameters:
        target_status (str): Moderation status to inspect ('quarantined', 'pending', 'rejected').
    """
    async with get_db_session() as session:
        # Fetch vocabulary items
        v_stmt = (
            select(VocabGroundTruth)
            .where(VocabGroundTruth.status == target_status)
            .order_by(VocabGroundTruth.created_at.desc())
        )
        v_records = list((await session.execute(v_stmt)).scalars().all())

        # Fetch grammar items
        g_stmt = (
            select(GrammarGroundTruth)
            .where(GrammarGroundTruth.status == target_status)
            .order_by(GrammarGroundTruth.created_at.desc())
        )
        g_records = list((await session.execute(g_stmt)).scalars().all())

    table = Table(title=f"Review Queue: Status = '{target_status}'")
    table.add_column("Type", style="cyan", no_wrap=True)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Title / Word", style="bold")
    table.add_column("Details", style="italic")
    table.add_column("Source", style="green")
    table.add_column("Reports", justify="right", style="red")
    table.add_column("Usage", justify="right")

    for v in v_records:
        detail = f"{v.definition_vi} ({v.part_of_speech})"
        table.add_row("Vocab", str(v.id)[:8] + "...", v.word, detail[:60], v.source, str(v.report_count), str(v.usage_count))

    for g in g_records:
        detail = f"{g.formula} | {g.usage_vi}"
        table.add_row("Grammar", str(g.id)[:8] + "...", g.title, detail[:60], g.source, str(g.report_count), str(g.usage_count))

    total = len(v_records) + len(g_records)
    console.print(table)
    console.print(f"[bold]Total records found:[/bold] {total}")


async def update_record_status(record_id_prefix: str, new_status: str) -> None:
    """
    Update the status of a vocabulary or grammar record by ID or ID prefix.

    Parameters:
        record_id_prefix (str): Full or partial UUID string.
        new_status (str): Target status ('verified', 'rejected', 'quarantined').
    """
    async with get_db_session() as session:
        # Search in vocab_ground_truth
        v_stmt = select(VocabGroundTruth)
        v_records = list((await session.execute(v_stmt)).scalars().all())
        target_v = [v for v in v_records if str(v.id).startswith(record_id_prefix)]

        if target_v:
            for v in target_v:
                v.status = new_status
                console.print(f"[green]Updated Vocab '{v.word}' ({v.id}) -> status = '{new_status}'[/green]")
            await session.commit()
            return

        # Search in grammar_ground_truth
        g_stmt = select(GrammarGroundTruth)
        g_records = list((await session.execute(g_stmt)).scalars().all())
        target_g = [g for g in g_records if str(g.id).startswith(record_id_prefix)]

        if target_g:
            for g in target_g:
                g.status = new_status
                console.print(f"[green]Updated Grammar '{g.title}' ({g.id}) -> status = '{new_status}'[/green]")
            await session.commit()
            return

        console.print(f"[bold red]No record matching ID prefix '{record_id_prefix}' found.[/bold red]")


async def edit_record_field(record_id_prefix: str, field_name: str, new_value: str) -> None:
    """
    Edit a specific field on a vocabulary or grammar record and promote to 'verified'.

    Parameters:
        record_id_prefix (str): Full or partial UUID.
        field_name (str): Column name to update.
        new_value (str): New content value.
    """
    async with get_db_session() as session:
        # Try vocab
        v_stmt = select(VocabGroundTruth)
        v_records = list((await session.execute(v_stmt)).scalars().all())
        for v in v_records:
            if str(v.id).startswith(record_id_prefix):
                if hasattr(v, field_name):
                    setattr(v, field_name, new_value)
                    v.status = "verified"
                    await session.commit()
                    console.print(f"[green]Edited Vocab '{v.word}': set {field_name} = '{new_value}', status = 'verified'[/green]")
                    return
                console.print(f"[bold red]VocabGroundTruth has no field '{field_name}'.[/bold red]")
                return

        # Try grammar
        g_stmt = select(GrammarGroundTruth)
        g_records = list((await session.execute(g_stmt)).scalars().all())
        for g in g_records:
            if str(g.id).startswith(record_id_prefix):
                if hasattr(g, field_name):
                    setattr(g, field_name, new_value)
                    g.status = "verified"
                    await session.commit()
                    console.print(f"[green]Edited Grammar '{g.title}': set {field_name} = '{new_value}', status = 'verified'[/green]")
                    return
                console.print(f"[bold red]GrammarGroundTruth has no field '{field_name}'.[/bold red]")
                return

        console.print(f"[bold red]No record matching ID prefix '{record_id_prefix}' found.[/bold red]")


def main() -> None:
    """CLI argument parser for admin moderation workflow."""
    parser = argparse.ArgumentParser(description="Admin review queue for quarantined and pending knowledge.")
    parser.add_argument("--list", choices=["quarantined", "pending", "rejected", "verified"], help="List records by status.")
    parser.add_argument("--accept", type=str, help="Promote record ID to 'verified'.")
    parser.add_argument("--reject", type=str, help="Demote record ID to 'rejected'.")
    parser.add_argument("--edit", type=str, help="Record ID to edit.")
    parser.add_argument("--field", type=str, help="Field name to edit.")
    parser.add_argument("--value", type=str, help="New value for edited field.")

    args = parser.parse_args()

    if args.list:
        asyncio.run(list_records(args.list))
    elif args.accept:
        asyncio.run(update_record_status(args.accept, "verified"))
    elif args.reject:
        asyncio.run(update_record_status(args.reject, "rejected"))
    elif args.edit and args.field and args.value:
        asyncio.run(edit_record_field(args.edit, args.field, args.value))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

