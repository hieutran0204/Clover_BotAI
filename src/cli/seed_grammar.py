"""
name: seed_grammar
description: CLI tool to seed core English grammar patterns and formulas into grammar_ground_truth table.
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import List

from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from src.db.models import GrammarGroundTruth
from src.db.session import get_db_session
from src.schemas.grammar import GrammarBatchSchema, GrammarSchema
from src.services.ai.embedding_service import EmbeddingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()


async def seed_grammar_from_file(file_path: Path) -> None:
    """
    Parse a JSON file containing GrammarSchema entries, generate embeddings, and insert new records.

    Parameters:
        file_path (Path): Path to the seed JSON file.
    """
    if not file_path.exists():
        console.print(f"[bold red]File not found:[/bold red] {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    if isinstance(raw_data, list):
        batch = GrammarBatchSchema(items=[GrammarSchema.model_validate(item) for item in raw_data])
    else:
        batch = GrammarBatchSchema.model_validate(raw_data)

    embedding_service = EmbeddingService()
    model_name = embedding_service.get_model_name()

    console.print(f"[bold cyan]Seeding {len(batch.items)} grammar patterns using model:[/bold cyan] [green]{model_name}[/green]")

    async with get_db_session() as session:
        # Check existing pattern keys to deduplicate
        stmt = select(GrammarGroundTruth.pattern_key)
        res = await session.execute(stmt)
        existing_keys = set(res.scalars().all())

        table = Table(title="Grammar Seeding Progress")
        table.add_column("Title", style="cyan")
        table.add_column("Pattern Key", style="magenta")
        table.add_column("CEFR", justify="center")
        table.add_column("Vector", justify="right")
        table.add_column("Status", style="green")

        inserted_count = 0
        skipped_count = 0

        for item in batch.items:
            if item.pattern_key in existing_keys:
                table.add_row(item.title, item.pattern_key, item.cefr_level, "-", "[yellow]Skipped (exists)[/yellow]")
                skipped_count += 1
                continue

            # Compute embedding for canonical grammar representation
            canonical_text = EmbeddingService.build_grammar_embedding_text(item)
            vector = await embedding_service.embed_document(canonical_text)

            record = GrammarGroundTruth(
                telegram_user_id=None,
                title=item.title.strip(),
                pattern_key=item.pattern_key.strip(),
                formula=item.formula.strip(),
                usage_vi=item.usage_vi.strip(),
                examples_json=[ex.model_dump() for ex in item.examples],
                common_mistakes_vi=item.common_mistakes_vi.strip(),
                cefr_level=item.cefr_level.strip(),
                embedding=vector,
                embedding_model=model_name,
                source="global_seed",
                status="verified",
                usage_count=0,
                report_count=0,
            )
            session.add(record)
            existing_keys.add(item.pattern_key)
            dim_str = str(len(vector)) if vector else "None"
            table.add_row(item.title, item.pattern_key, item.cefr_level, dim_str, "✅ Inserted")
            inserted_count += 1

        await session.commit()
        console.print(table)
        console.print(f"[bold green]Seeding complete: {inserted_count} inserted, {skipped_count} skipped.[/bold green]")


def main() -> None:
    """CLI entrypoint for seeding grammar rules."""
    parser = argparse.ArgumentParser(description="Seed grammar patterns into PostgreSQL.")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("data/seeds/sample_grammar.json"),
        help="Path to grammar JSON seed file.",
    )
    args = parser.parse_args()
    asyncio.run(seed_grammar_from_file(args.file))


if __name__ == "__main__":
    main()

