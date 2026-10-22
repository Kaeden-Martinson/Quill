"""Settings, overridable with environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("QUILL_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "quill.db"
FRONTEND_DIR = ROOT / "frontend"

OLLAMA_URL = os.environ.get("QUILL_OLLAMA_URL", "http://127.0.0.1:11434")
# Line edits. Swap for a fine-tuned model once one beats the default on training/eval.py.
MODEL = os.environ.get("QUILL_MODEL", "gemma4:e4b")
# Big-picture feedback is a different task; the fine-tuned editors are only trained on line edits.
OVERVIEW_MODEL = os.environ.get("QUILL_OVERVIEW_MODEL", "gemma4:e4b")

# Shared passcode for family and friends. Set it before sharing the link.
PASSCODE = os.environ.get("QUILL_PASSCODE", "change-me")

# Paragraphs reviewed at once; keep low so one laptop GPU isn't swamped.
MAX_CONCURRENT_REVIEWS = int(os.environ.get("QUILL_MAX_CONCURRENT", "2"))
