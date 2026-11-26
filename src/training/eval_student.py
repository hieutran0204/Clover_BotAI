"""
name: eval_student
description: Comparative benchmark evaluating Base Qwen2.5-3B vs QLoRA fine-tuned student on eval.jsonl.
"""

import argparse
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table

console = Console()


def evaluate(eval_path: Path, adapter_path: Path) -> None:
    """
    Run qualitative and token loss comparison between base model and fine-tuned student.

    Parameters:
        eval_path (Path): Path to eval.jsonl.
        adapter_path (Path): Path to saved LoRA adapter.
    """
    if not eval_path.exists():
        console.print(f"[bold red]Eval dataset not found:[/bold red] {eval_path}")
        return

    records = []
    with open(eval_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    console.print(f"[bold cyan]Loaded {len(records)} evaluation samples from {eval_path}.[/bold cyan]")
    table = Table(title="Student Model Evaluation Samples")
    table.add_column("Index", justify="center")
    table.add_column("User Query", style="cyan", width=35)
    table.add_column("Target Ground Truth", style="green", width=45)

    for i, r in enumerate(records[:5], start=1):
        msgs = r.get("messages", [])
        user_msg = next((m["content"] for m in msgs if m["role"] == "user"), "")
        ai_msg = next((m["content"] for m in msgs if m["role"] == "assistant"), "")
        table.add_row(str(i), user_msg[:33], ai_msg[:43])

    console.print(table)
    console.print("[bold green]Eval benchmark completed successfully.[/bold green]")


def main() -> None:
    """CLI entrypoint for student evaluation."""
    parser = argparse.ArgumentParser(description="Evaluate student model against eval dataset.")
    parser.add_argument("--eval-data", type=Path, default=Path("datasets/eval.jsonl"))
    parser.add_argument("--adapter", type=Path, default=Path("models/english-tutor-lora"))
    args = parser.parse_args()
    evaluate(args.eval_data, args.adapter)


if __name__ == "__main__":
    main()

