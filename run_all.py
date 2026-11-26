"""
name: run_all
description: Production supervisor entrypoint that runs both the Telegram bot and FastAPI Web Admin in a single container with auto-restart resilience.
"""

import os
import signal
import subprocess
import sys
import time


def main() -> None:
    """
    Launch both the Telegram Bot and the FastAPI Web Admin processes concurrently,
    auto-restarting any transient failures (such as temporary Telegram conflicts).
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

    shutting_down = False

    def handle_shutdown(sig_num: int, _frame: object) -> None:
        nonlocal shutting_down
        shutting_down = True
        print(f"\n[!] Caught shutdown signal ({sig_num}). Gracefully terminating sub-processes...")
        bot_proc.terminate()
        admin_proc.terminate()
        try:
            bot_proc.wait(timeout=5)
            admin_proc.wait(timeout=5)
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Monitor loop: auto-restart transient crashes
    while not shutting_down:
        bot_status = bot_proc.poll()
        if bot_status is not None:
            print(f"[WARN] Telegram bot exited with code {bot_status}. Auto-restarting in 5 seconds...")
            time.sleep(5)
            if not shutting_down:
                bot_proc = subprocess.Popen([python_exe, "main.py"])
                print(f"[*] Telegram Bot respawned (new PID: {bot_proc.pid})")

        admin_status = admin_proc.poll()
        if admin_status is not None:
            print(f"[WARN] Web Admin exited with code {admin_status}. Auto-restarting in 5 seconds...")
            time.sleep(5)
            if not shutting_down:
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
                print(f"[*] Web Admin respawned (new PID: {admin_proc.pid})")

        time.sleep(3)


if __name__ == "__main__":
    main()
