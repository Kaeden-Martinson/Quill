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

# How each job picks its next words, sent to Ollama with every request (overriding the model's
# own defaults). Set QUILL_<JOB>_<SETTING> in quill.env, e.g. QUILL_DRAFT_TEMPERATURE=0.8.
# Anything left unset falls back to the model's Modelfile defaults.
SAMPLING_SETTINGS = {"temperature": float, "top_p": float, "top_k": int, "min_p": float,
                     "repeat_penalty": float, "seed": int}


def sampling(job, **defaults):
    options = dict(defaults)
    for name, kind in SAMPLING_SETTINGS.items():
        key = f"QUILL_{job}_{name.upper()}"
        raw = os.environ.get(key, "").strip()
        if raw:
            try:
                options[name] = kind(raw)
            except ValueError:
                raise SystemExit(f"{key}={raw!r} in quill.env isn't a {kind.__name__}.") from None
    return options


# Line edits: temperature 0, so the same paragraph always gets the same fixes. On the
# confirmation set it beat 0.3 (93% vs 90% of mistakes fixed, half the unneeded changes).
# training/reliability.py and eval.py score the editor with these same settings.
EDIT_OPTIONS = sampling("EDIT", temperature=0)
# The letter about the whole essay: a little looser so the comments don't read canned.
LETTER_OPTIONS = sampling("LETTER", temperature=0.4, top_p=0.9)
# Drafting: warmer, for natural variety in wording and sentence shape; the repeat penalty
# keeps longer drafts from circling back to the same phrases.
DRAFT_OPTIONS = sampling("DRAFT", temperature=0.75, top_p=0.9, repeat_penalty=1.1)
