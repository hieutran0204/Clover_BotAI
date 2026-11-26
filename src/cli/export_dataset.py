"""
name: export_dataset
description: Exports strictly verified Ground Truth conversations to train.jsonl (90%) and eval.jsonl (10%) for QLoRA fine-tuning.
"""

import argparse
import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List

from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from src.db.models import ChatLogs, GrammarGroundTruth, VocabGroundTruth
from src.db.session import get_db_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()

TEACHER_SYSTEM_PROMPT = (
    "You are a friendly, natural bilingual English study buddy chatting on Telegram. "
    "Explain concepts concisely, use everyday examples, and avoid robotic AI disclaimers."
)


async def export_training_dataset(output_dir: Path, split_ratio: float = 0.9, seed: int = 42) -> None:
    """
    Query strictly verified Ground Truth and golden chat logs, serialize into ChatML format,
    and split into train.jsonl and eval.jsonl.

    Parameters:
        output_dir (Path): Output directory for JSONL files.
        split_ratio (float): Fraction of data allocated to train set (default: 0.9).
        seed (int): Random seed for reproducible dataset splitting.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    random.seed(seed)

    chatml_records: List[Dict[str, Any]] = []

    async with get_db_session() as session:
        # 1. Export strictly verified_golden chat logs
        stmt_chat = (
            select(ChatLogs)
            .where(ChatLogs.status == "verified_golden")
            .order_by(ChatLogs.created_at.asc())
        )
        chat_rows = list((await session.execute(stmt_chat)).scalars().all())

        for chat in chat_rows:
            turns = chat.turns_json
            if not turns:
                continue

            messages = [{"role": "system", "content": TEACHER_SYSTEM_PROMPT}]
            for t in turns:
                # Handle ChatML format {"role": ..., "content": ...}
                if "role" in t and "content" in t:
                    messages.append({"role": t["role"], "content": t["content"]})
                # Handle legacy ShareGPT format {"from": ..., "value": ...}
                elif "from" in t and "value" in t:
                    role = "user" if t["from"] == "human" else "assistant"
                    messages.append({"role": role, "content": t["value"]})

            if len(messages) >= 3:
                chatml_records.append({"messages": messages})

        # 2. Synthesize verified vocabulary Q&A pairs
        stmt_vocab = (
            select(VocabGroundTruth)
            .where(VocabGroundTruth.status == "verified")
            .order_by(VocabGroundTruth.created_at.asc())
        )
        vocab_rows = list((await session.execute(stmt_vocab)).scalars().all())

        for v in vocab_rows:
            # Meaning explanation Q&A
            user_q1 = f"Từ '{v.word}' nghĩa là gì và phát âm thế nào?"
            ai_a1 = (
                f"Từ <b>{v.word}</b> <code>{v.phonetic}</code> ({v.part_of_speech}, {v.cefr_level}):\n"
                f"🇻🇳 {v.definition_vi}\n"
                f"🇬🇧 {v.definition_en}\n\n"
                f"💬 <b>Ví dụ:</b>\n"
                f"<i>{v.example_sentence}</i>\n"
                f"↳ {v.example_translation}"
            )
            chatml_records.append({
                "messages": [
                    {"role": "system", "content": TEACHER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_q1},
                    {"role": "assistant", "content": ai_a1},
                ]
            })

            # Sentence analysis Q&A
            user_q2 = f"Giải thích câu này giúp tao: \"{v.example_sentence}\""
            ai_a2 = (
                f"Câu này có nghĩa là: \"{v.example_translation}\".\n\n"
                f"Trong câu, từ khóa nổi bật là <b>{v.word}</b> ({v.part_of_speech}): {v.definition_vi}."
            )
            chatml_records.append({
                "messages": [
                    {"role": "system", "content": TEACHER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_q2},
                    {"role": "assistant", "content": ai_a2},
                ]
            })

        # 3. Synthesize verified grammar Q&A pairs
        stmt_grammar = (
            select(GrammarGroundTruth)
            .where(GrammarGroundTruth.status == "verified")
            .order_by(GrammarGroundTruth.created_at.asc())
        )
        grammar_rows = list((await session.execute(stmt_grammar)).scalars().all())

        for g in grammar_rows:
            user_q = f"Giải thích cấu trúc ngữ pháp '{g.title}'"
            ex_str = ""
            if g.examples_json:
                ex0 = g.examples_json[0]
                ex_str = f"\n\n💬 <b>Ví dụ:</b>\n<i>{ex0.get('sentence', '')}</i>\n↳ {ex0.get('translation', '')}"

            ai_a = (
                f"Cấu trúc <b>{g.title}</b> ({g.cefr_level}):\n"
                f"📐 <b>Công thức:</b> <code>{g.formula}</code>\n"
                f"💡 <b>Cách dùng:</b> {g.usage_vi}"
                f"{ex_str}"
            )
            chatml_records.append({
                "messages": [
                    {"role": "system", "content": TEACHER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_q},
                    {"role": "assistant", "content": ai_a},
                ]
            })

    total = len(chatml_records)
    if not total:
        console.print("[bold red]No verified golden records found to export![/bold red]")
        return

    # Shuffle deterministically and split
    random.shuffle(chatml_records)
    split_idx = int(total * split_ratio)
    train_records = chatml_records[:split_idx]
    eval_records = chatml_records[split_idx:]

    train_path = output_dir / "train.jsonl"
    eval_path = output_dir / "eval.jsonl"

    with open(train_path, "w", encoding="utf-8") as f:
        for r in train_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(eval_path, "w", encoding="utf-8") as f:
        for r in eval_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    table = Table(title="Dataset Export Summary")
    table.add_column("Dataset File", style="cyan")
    table.add_column("Record Count", justify="right", style="green")
    table.add_column("Percentage", justify="right")
    table.add_column("Path", style="dim")

    table.add_row("train.jsonl", str(len(train_records)), f"{split_ratio * 100:.0f}%", str(train_path))
    table.add_row("eval.jsonl", str(len(eval_records)), f"{(1 - split_ratio) * 100:.0f}%", str(eval_path))
    table.add_row("Total", str(total), "100%", str(output_dir))

    console.print(table)
    console.print(f"[bold green]Strictly verified training dataset exported successfully![/bold green]")


def main() -> None:
    """CLI entrypoint for dataset export."""
    parser = argparse.ArgumentParser(description="Export strictly verified knowledge to ChatML train/eval datasets.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("datasets"),
        help="Directory to save train.jsonl and eval.jsonl.",
    )
    parser.add_argument(
        "--split",
        type=float,
        default=0.9,
        help="Train split ratio (default: 0.9).",
    )
    args = parser.parse_args()
    asyncio.run(export_training_dataset(args.output_dir, split_ratio=args.split))


if __name__ == "__main__":
    main()

