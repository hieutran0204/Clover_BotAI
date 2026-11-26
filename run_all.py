"""
name: run_all
description: Production supervisor entrypoint that runs both the Telegram bot and FastAPI Web Admin in a single container.
"""

import os
import signal
import subprocess
import sys
import time


def main() -> None:
    """
    Launch both the Telegram Bot and the FastAPI Web Admin processes concurrently.
    """
    port = os.getenv("PORT", os.getenv("ADMIN_PORT", "8000"))
    python_exe = sys.executable

    print("=" * 60)
    print("🚀 Starting Clover_BotAI Dual Production Runner")
    print(f"[*] Port configured for Web Admin: {port}")
    print("=" * 60)

    # 1. Start Telegram Bot in background
    bot_proc = subprocess.Popen([python_exe, "main.py"])
    print(f"[*] Telegram Bot process spawned (PID: {bot_proc.pid})")

    # 2. Start FastAPI Web Admin Dashboard
    admin_proc = subprocess.Popen([
        python_exe,
        "-m",
        "uvicorn",
        "src.admin.app:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
    ])
    print(f"[*] FastAPI Web Admin process spawned (PID: {admin_proc.pid})")

    def handle_shutdown(sig_num: int, _frame: object) -> None:
        print(f"\n[!] Caught shutdown signal ({sig_num}). Gracefully terminating sub-processes...")
        bot_proc.terminate()
        admin_proc.terminate()
        bot_proc.wait(timeout=5)
        admin_proc.wait(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Monitor both processes; if either dies, log and terminate cleanly
    while True:
        bot_status = bot_proc.poll()
        if bot_status is not None:
            print(f"[ERROR] Telegram bot process exited with code {bot_status}. Shutting down admin...")
            admin_proc.terminate()
            sys.exit(bot_status)

        admin_status = admin_proc.poll()
        if admin_status is not None:
            print(f"[ERROR] Web Admin process exited with code {admin_status}. Shutting down bot...")
            bot_proc.terminate()
            sys.exit(admin_status)

        time.sleep(2)


if __name__ == "__main__":
    main()
