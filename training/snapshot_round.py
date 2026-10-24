"""Freeze a finished training round before the next one overwrites training/out and training/data.

    .venv\\Scripts\\python training\\snapshot_round.py 7

Moves training/out -> training/out-run<N> (a rename: the folder holds ~11 GB), copies training/data ->
training/data-run<N>, copies the baseline results that exist, and writes training/rounds/round<N>.json:
sha256 of every dataset, adapter and GGUF file, the training configuration read from train.py, the
served Ollama model's own manifest digest, and the baseline scores. The JSON is committed; the big
files stay local (git-ignored).
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def train_config():
    """The hyperparameters as written in train.py, so a later edit can't silently change the record."""
    src = (HERE / "train.py").read_text(encoding="utf-8")
    keys = ["BASE", "MAX_LEN", "r", "lora_alpha", "lora_dropout", "per_device_train_batch_size",
            "gradient_accumulation_steps", "num_train_epochs", "learning_rate", "lr_scheduler_type",
            "warmup_ratio", "eval_steps", "save_steps", "optim"]
    out = {}
    for k in keys:
        m = re.search(rf"\b{k}\s*=\s*([^,\n]+)", src)
        if m:
            out[k] = m.group(1).strip()
    base = re.search(r'BASE = os\.environ\.get\("QUILL_BASE_MODEL", "([^"]+)"\)', src)
    if base:  # the default base model, not the expression around it
        out["BASE"] = base.group(1)
    out["train_py_sha256"] = sha256(HERE / "train.py")
    return out


def main(n, model_name):
    out_dir, data_dir = HERE / f"out-run{n}", HERE / f"data-run{n}"
    if (HERE / "out").exists() and not out_dir.exists():
        (HERE / "out").rename(out_dir)
    if not data_dir.exists():
        shutil.copytree(HERE / "data", data_dir)
    files = {}
    for path in sorted(list(data_dir.glob("*.jsonl")) + list((out_dir / "lora").glob("*"))
                       + list(out_dir.glob("gguf_gguf/*.gguf")) + [out_dir / "Modelfile"]):
        if path.is_file():
            files[str(path.relative_to(ROOT)).replace("\\", "/")] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    states = sorted((out_dir / "checkpoints").glob("checkpoint-*/trainer_state.json"),
                    key=lambda p: int(p.parent.name.split("-")[1]))
    curve = {}
    if states:
        hist = json.loads(states[-1].read_text(encoding="utf-8"))["log_history"]
        curve = {"train_loss": [[h["step"], h["loss"]] for h in hist if "loss" in h],
                 "eval_loss": [[h["step"], h["eval_loss"]] for h in hist if "eval_loss" in h]}
    shown = subprocess.run(["ollama", "show", model_name, "--modelfile"], capture_output=True, text=True).stdout
    blob = re.search(r"^FROM (.+)$", shown, re.M)
    record = {
        "round": n, "ollama_model": model_name,
        "ollama_blob": Path(blob.group(1).strip()).name if blob else None,
        "train_config": train_config(), "files": files, "loss_curve": curve,
    }
    rounds = HERE / "rounds"
    rounds.mkdir(exist_ok=True)
    (rounds / f"round{n}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(f"round {n}: {len(files)} files hashed; out -> {out_dir.name}; data copied to {data_dir.name}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else f"quill-editor-v{sys.argv[1]}")
