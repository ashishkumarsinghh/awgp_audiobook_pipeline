#!/usr/bin/env python3
"""
Universal Cross-Platform Pipeline Launcher (Windows, macOS, Linux, WSL)
Starts both FastAPI Backend (:8000) and Vite Frontend (:5173).
Usage:
    python dev.py
"""

import os
import sys
import subprocess
import signal
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def get_npm_cmd():
    if sys.platform == "win32":
        return "npm.cmd"
    return "npm"


def main():
    print("=" * 54)
    print("   AWGP Audiobook Production Pipeline Launcher       ")
    print("=" * 54)

    # 1. Backend command
    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "api:app",
        "--reload",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]

    # 2. Frontend command
    npm_executable = get_npm_cmd()
    frontend_cmd = [npm_executable, "run", "dev", "--", "--host", "0.0.0.0"]

    processes = []

    def cleanup(signum=None, frame=None):
        print("\nStopping all services gracefully...")
        for p in processes:
            if p.poll() is None:
                try:
                    if sys.platform == "win32":
                        p.terminate()
                    else:
                        p.send_signal(signal.SIGTERM)
                except Exception:
                    pass
        for p in processes:
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
        print("All services stopped cleanly. Goodbye!")
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        print("[1/2] Starting FastAPI Backend on http://localhost:8000...")
        backend_p = subprocess.Popen(backend_cmd, cwd=str(PROJECT_ROOT))
        processes.append(backend_p)

        time.sleep(1.5)

        print("[2/2] Starting Vite Frontend on http://localhost:5173...")
        frontend_p = subprocess.Popen(frontend_cmd, cwd=str(FRONTEND_DIR))
        processes.append(frontend_p)

        print("\n" + "=" * 54)
        print("  ✓ Backend running at:  http://localhost:8000")
        print("  ✓ API Docs running at: http://localhost:8000/docs")
        print("  ✓ Frontend running at: http://localhost:5173")
        print("=" * 54)
        print("Press [Ctrl+C] to stop all services.\n")

        # Keep parent alive and monitor children
        while True:
            for p in processes:
                if p.poll() is not None:
                    # One of the processes terminated unexpectedly
                    cleanup()
            time.sleep(0.5)

    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
