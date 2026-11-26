"""
name: reembed_vocab
description: CLI tool to recompute vector embeddings for all vocab_ground_truth records using nomic-embed-text.
"""

import asyncio
import logging
from typing import List

from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from src.db.models import VocabGroundTruth
from src.db.session import get_db_session
from src.schemas.vocab import VocabSchema
from src.services.ai.embedding_service import EmbeddingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()


async def reembed_all_vocab() -> None:
    """
    Fetch all vocabulary records and recompute 768-dim embeddings with nomic-embed-text.
    """
    embedding_service = EmbeddingService()
    target_model = embedding_service.get_model_name()
    console.print(f"[bold cyan]Starting vocab re-embedding with model:[/bold cyan] [green]{target_model}[/green]")

    async with get_db_session() as session:
        stmt = select(VocabGroundTruth).order_by(VocabGroundTruth.word.asc())
        result = await session.execute(stmt)
        records: List[VocabGroundTruth] = list(result.scalars().all())

        if not records:
            console.print("[yellow]No vocabulary records found in database.[/yellow]")
            return

        table = Table(title=f"Re-embedding {len(records)} Vocabulary Items")
        table.add_column("Word", style="cyan", no_wrap=True)
        table.add_column("Old Model", style="yellow")
        table.add_column("New Model", style="green")
        table.add_column("Vector Dim", justify="right")
        table.add_column("Status", style="magenta")

        for record in records:
            # Build canonical representation
            schema = VocabSchema(
                word=record.word,
                phonetic=record.phonetic,
                part_of_speech=record.part_of_speech,
                definition_vi=record.definition_vi,
                definition_en=record.definition_en,
                example_sentence=record.example_sentence,
                example_translation=record.example_translation,
                cefr_level=record.cefr_level,
                quiz_question=record.quiz_question,
                quiz_options=record.quiz_options,
                quiz_correct_index=record.quiz_correct_index,
            )
            canonical_text = EmbeddingService.build_vocab_embedding_text(schema)
            vector = await embedding_service.embed_document(canonical_text)

            old_model = record.embedding_model or "none/gemini"
            dim_str = str(len(vector)) if vector else "None"

            if vector is not None:
                record.embedding = vector
                record.embedding_model = target_model
                table.add_row(record.word, old_model, target_model, dim_str, "✅ Updated")
            else:
                table.add_row(record.word, old_model, target_model, "0", "❌ Failed")

        await session.commit()
        console.print(table)
        console.print(f"[bold green]Successfully re-embedded {len(records)} vocabulary items![/bold green]")


def main() -> None:
    """CLI entrypoint for re-embedding vocabulary records."""
    asyncio.run(reembed_all_vocab())


if __name__ == "__main__":
    main()

