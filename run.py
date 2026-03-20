"""
Job Applicator – entry point
Run:  python run.py
"""
import subprocess
import sys
import os
import webbrowser
import time
import threading
from pathlib import Path

BASE_DIR   = Path(__file__).parent
SETUP_FLAG = BASE_DIR / "data" / ".setup_done"


def ensure_dirs():
    for d in ["data", "output", "frontend", "backend"]:
        (BASE_DIR / d).mkdir(exist_ok=True)


def install_dependencies():
    print("📦  Installing dependencies (first run only)...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
         "--prefer-binary", "-q"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        print("\n❌  Dependency install failed.")
        print(f"    Try: {sys.executable} -m pip install -r requirements.txt --prefer-binary")
        sys.exit(1)
    print("✅  Dependencies ready.")


def install_playwright():
    print("🌐  Installing Playwright Chromium (first run only)...")
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("✅  Playwright Chromium ready.")
    else:
        print("⚠️   Playwright install issue:", result.stderr[:200])


def check_env():
    from dotenv import load_dotenv
    load_dotenv()
    missing = [k for k in ["OPENAI_API_KEY", "SEEK_EMAIL", "SEEK_PASSWORD"] if not os.getenv(k)]
    if missing:
        print(f"❌  Missing in .env: {', '.join(missing)}")
        sys.exit(1)
    print("✅  Environment ready.")


def init_db():
    sys.path.insert(0, str(BASE_DIR))
    from backend.database import init_db as _init
    _init()
    print("✅  Database ready.")


def first_time_setup():
    """Run once, then write a marker so subsequent starts skip this."""
    install_dependencies()
    install_playwright()
    SETUP_FLAG.touch()
    print("✅  Setup complete — future starts will be instant.\n")


def start_server():
    print("🚀  Starting Job Applicator → http://localhost:8000\n")
    threading.Thread(
        target=lambda: (time.sleep(1.5), webbrowser.open("http://localhost:8000")),
        daemon=True
    ).start()

    os.chdir(BASE_DIR)
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
    ])


if __name__ == "__main__":
    os.chdir(BASE_DIR)
    ensure_dirs()

    if not SETUP_FLAG.exists():
        first_time_setup()

    check_env()
    init_db()
    start_server()
