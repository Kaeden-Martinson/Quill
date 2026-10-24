"""Paths and small helpers shared by the generator-evaluation scripts (plan.md).

Everything this experiment writes lives under training/generation_eval (committed: plan, prompts for
the Quill-genre family, scripts, manifests, summaries) or data/generation_eval (local only: generated
corpora, licensed human essays, PERSUADE-derived prompts, detector exports). Nothing here touches the
editor rounds, the sealed editor test or the live app's database.
"""
import hashlib
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PROMPTS = HERE / "prompts"
LOCAL = ROOT / "data" / "generation_eval"
CORPUS = LOCAL / "corpus"        # generated drafts (pipelines A and B)
HUMAN = LOCAL / "human"          # human-written controls
DETECT = LOCAL / "detectors"     # detector exports as received
RATINGS = HERE / "ratings"       # blind sheets' keys and imported ratings
ACCESS_LOG = HERE / "eval_access_log.jsonl"
SPLITS = ("dev", "eval")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path):
    """Rows of a JSONL file; a malformed line raises with its line number instead of being skipped."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{n}: malformed JSON ({exc})") from None
    return rows


def write_jsonl(path, rows, overwrite=False):
    path = Path(path)
    if path.exists() and not overwrite:
        raise SystemExit(f"{path} exists; this experiment never overwrites outputs. Use a new run name.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def require_unsealed(split, what):
    """The evaluation split is locked until development decisions are complete (plan.md section 4).
    Using it needs QUILL_GEN_UNSEAL=1, and every use is logged."""
    if split != "eval":
        return
    if os.environ.get("QUILL_GEN_UNSEAL") != "1":
        raise SystemExit(f"The eval split is locked. {what} on it needs QUILL_GEN_UNSEAL=1, "
                         "only after development decisions are complete (plan.md).")
    with open(ACCESS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"opened": time.strftime("%Y-%m-%d %H:%M:%S"), "what": what}) + "\n")


def words(text):
    return len(text.split())
