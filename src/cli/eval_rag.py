"""
name: eval_rag
description: Benchmark evaluation runner measuring Hit Rate@3 on positive test queries and False-Hit Rate on should-miss negative queries.
"""

import asyncio
import json
import logging
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.db.session import get_db_session
from src.services.ai.rag_retriever import KnowledgeRetriever

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
console = Console()


async def run_benchmark(benchmark_path: Path) -> None:
    """
    Run evaluation benchmark on positive and negative test cases.

    Parameters:
        benchmark_path (Path): Path to JSON file containing positive and negative test cases.
    """
    if not benchmark_path.exists():
        console.print(f"[bold red]Benchmark file not found:[/bold red] {benchmark_path}")
        return

    with open(benchmark_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pos_cases = data.get("positive_cases", [])
    neg_cases = data.get("negative_cases", [])

    retriever = KnowledgeRetriever()
    console.print(f"[bold cyan]Starting Hybrid RAG Benchmark ({len(pos_cases)} Positive, {len(neg_cases)} Negative)...[/bold cyan]")

    async with get_db_session() as session:
        # 1. Evaluate Positive Cases (Target: Hit Rate@3 >= 80%)
        pos_table = Table(title="Positive Evaluation (Top-3 Retrieval Accuracy)")
        pos_table.add_column("Query", style="cyan", width=40)
        pos_table.add_column("Expected", style="magenta", width=22)
        pos_table.add_column("Top-1 Surfaced", style="yellow", width=22)
        pos_table.add_column("Rerank Score", justify="right")
        pos_table.add_column("Result", justify="center")

        pos_success = 0
        for case in pos_cases:
            query = case["query"]
            expected = case["expected_target"].lower()
            top_items, is_hit, _ = await retriever.search_and_rerank(session, query)

            top_titles = [it.title.lower() for it in top_items]
            top_keys = [it.metadata.get("pattern_key", "").lower() for it in top_items]
            all_surfaced = top_titles + top_keys

            hit_in_top3 = any(expected in s or s in expected for s in all_surfaced)
            top1_title = top_items[0].title if top_items else "NONE"
            top1_score = f"{top_items[0].rerank_score:.3f}" if top_items else "0.0"

            if is_hit and hit_in_top3:
                pos_success += 1
                status = "[green]✅ HIT@3[/green]"
            elif hit_in_top3:
                status = "[yellow]⚠️ Top-3 but under threshold[/yellow]"
            else:
                status = "[red]❌ MISS[/red]"

            pos_table.add_row(query[:38], expected[:20], top1_title[:20], top1_score, status)
            console.print(f"  [cyan]{len(pos_table.rows)}/{len(pos_cases)}[/cyan] {status} - {query[:35]} -> top1: [yellow]{top1_title}[/yellow] ({top1_score})")

        # 2. Evaluate Negative Cases (Target: False-Hit Rate < 5%)
        neg_table = Table(title="Negative Evaluation (Out-of-Scope / Should-Miss Rejection)")
        neg_table.add_column("Out-of-Scope Query", style="cyan", width=45)
        neg_table.add_column("Topic", style="dim", width=25)
        neg_table.add_column("Top-1 Score", justify="right")
        neg_table.add_column("Gate Result", justify="center")

        false_hits = 0
        for case in neg_cases:
            query = case["query"]
            desc = case.get("description", "")
            top_items, is_hit, _ = await retriever.search_and_rerank(session, query)

            top1_score = f"{top_items[0].rerank_score:.3f}" if top_items else "0.0"
            if is_hit:
                false_hits += 1
                gate_result = "[bold red]🚨 FALSE HIT (Leaked)[/bold red]"
            else:
                gate_result = "[green]🛡️ BLOCKED (Passed Gate)[/green]"

            neg_table.add_row(query[:43], desc[:23], top1_score, gate_result)
            console.print(f"  [dim]{len(neg_table.rows)}/{len(neg_cases)}[/dim] {gate_result} - {query[:35]} (top1: {top1_score})")

    console.print(pos_table)
    console.print(neg_table)

    hit_rate = (pos_success / len(pos_cases)) * 100 if pos_cases else 0.0
    false_hit_rate = (false_hits / len(neg_cases)) * 100 if neg_cases else 0.0

    summary = Table(title="Final Benchmark Summary")
    summary.add_column("Metric", style="bold")
    summary.add_column("Target Bar", justify="center")
    summary.add_column("Achieved", justify="center", style="bold")
    summary.add_column("Status", justify="center")

    pos_pass = hit_rate >= 80.0
    summary.add_row(
        "Positive Hit Rate@3",
        ">= 80.0%",
        f"{hit_rate:.1f}% ({pos_success}/{len(pos_cases)})",
        "[green]PASSED[/green]" if pos_pass else "[red]FAILED[/red]",
    )

    neg_pass = false_hit_rate <= 5.0
    summary.add_row(
        "Negative False-Hit Rate",
        "<= 5.0%",
        f"{false_hit_rate:.1f}% ({false_hits}/{len(neg_cases)})",
        "[green]PASSED[/green]" if neg_pass else "[red]FAILED[/red]",
    )

    console.print(summary)


def main() -> None:
    """CLI entrypoint for running RAG accuracy evaluation."""
    asyncio.run(run_benchmark(Path("datasets/eval_benchmark.json")))


if __name__ == "__main__":
    main()
