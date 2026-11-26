"""
name: sanitize_logs
description: CLI entrypoint to run SanitizerService over raw chat_logs and promote clean conversations to verified_golden.
"""

from __future__ import annotations

import argparse
import asyncio

from src.db.session import get_db_session
from src.services.sanitizer_service import SanitizerService


async def _run(limit: int) -> None:
    """
    Execute pending log sanitization inside a database transaction.

    Parameters:
        limit (int): Maximum raw log records to scan in one run.
    """
    async with get_db_session() as session:
        stats = await SanitizerService.sanitize_pending_logs(session=session, limit=limit)

    print(
        f"[SANITIZE] scanned={stats.total_scanned}, "
        f"verified_golden={stats.verified}, rejected={stats.rejected}"
    )
    if stats.rejection_breakdown:
        print(f"Rejection reasons: {stats.rejection_breakdown}")


def main() -> None:
    """
    Parse arguments and run chat log sanitization.
    """
    parser = argparse.ArgumentParser(
        description="Sanitize raw chat_logs rows into verified_golden or rejected."
    )
    parser.add_argument("--limit", type=int, default=500, help="Max raw rows to scan (default: 500).")
    args = parser.parse_args()
    asyncio.run(_run(limit=args.limit))


if __name__ == "__main__":
    main()

