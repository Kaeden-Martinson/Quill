"""Dataset and training audit for the line editor's fine-tuning pipeline.

    .venv\\Scripts\\python training\\audit_pipeline.py

Reads only what's in the repository: training/data/{train,val}.jsonl, the evaluation sets, the
human comparison corpus, and the trainer_state.json logs Hugging Face saved with each run's
checkpoints. Prints the facts; interpretation is in training/writing_eval/AUDIT.md.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import writing_metrics as wm  # noqa: E402

GENERIC = "No writing samples yet"


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def paragraph_of(example):
    user = example["messages"][1]["content"]
    return user.split('Paragraph:\n"""\n', 1)[1].rsplit('\n"""', 1)[0]


def source_of(example):
    user = example["messages"][1]["content"]
    if GENERIC in user:
        return "coedit"  # (plus the few app-feedback rows from writers with no samples)
    return "casual"


def shingles(text, n=5):
    toks = wm.words(text)
    return {tuple(toks[i:i + n]) for i in range(max(1, len(toks) - n + 1))}


def near_duplicates(queries, pool, threshold=0.5, n=5):
    """For each query text, whether some pool text shares >= threshold of the query's word 5-grams.
    An inverted index keeps this fast enough for ~10k paragraphs."""
    index = defaultdict(set)
    pool_sh = [shingles(t, n) for t in pool]
    for i, sh in enumerate(pool_sh):
        for g in sh:
            index[g].add(i)
    hits = []
    for q in queries:
        sh = shingles(q, n)
        counts = Counter(i for g in sh for i in index.get(g, ()))
        best = max((c / len(sh) for c in counts.values()), default=0.0)
        hits.append(best >= threshold)
    return hits


def section(title):
    print(f"\n=== {title}")


def dataset_audit():
    train, val = load(HERE / "data/train.jsonl"), load(HERE / "data/val.jsonl")
    section("splits")
    print(f"train {len(train)}, val {len(val)} (val is a random 5% of one shuffled pool; build_dataset.py)")
    for name, rows in (("train", train), ("val", val)):
        c = Counter(source_of(r) for r in rows)
        print(f"  {name}: {dict(c)}")

    section("input-output consistency (train)")
    n_edits = quote_missing = unchanged = 0
    cats = Counter()
    goals = Counter()
    for r in train:
        para = paragraph_of(r)
        goals[(source_of(r), r["messages"][1]["content"].split("Essay goal: ", 1)[1].split("\n", 1)[0])] += 1
        for s in json.loads(r["messages"][2]["content"])["suggestions"]:
            n_edits += 1
            quote_missing += s["original"] not in para
            unchanged += s["revised"] == s["original"]
            cats[s["category"]] += 1
    print(f"  {n_edits} edits; quote not found in its paragraph: {quote_missing}; revised == original: {unchanged}")
    print(f"  categories: {dict(cats)}")
    casual_goals = Counter({g: c for (src, g), c in goals.items() if src == "casual"})
    print(f"  'Essay goal' on casual examples (picked at random, independent of the paragraph): {dict(casual_goals)}")
    print(f"  'Essay goal' on CoEdIT examples: {dict(Counter({g: c for (src, g), c in goals.items() if src == 'coedit'}))}")

    section("length vs max_seq_length 2048")
    lengths = [sum(len(m["content"]) for m in r["messages"]) for r in train]
    # Qwen averages about 4 characters per English token; 3.5 is a conservative estimate.
    est = sorted(int(l / 3.5) for l in lengths)
    print(f"  estimated tokens per example: median {est[len(est) // 2]}, max {est[-1]}; "
          f"over 2048: {sum(e > 2048 for e in est)}")

    section("duplicates")
    paras = [paragraph_of(r) for r in train]
    print(f"  exact duplicate paragraphs in train: {len(paras) - len(set(paras))}")
    pairs = Counter(json.dumps(r["messages"][1:], ensure_ascii=False) for r in train)
    print(f"  exact duplicate whole examples in train: {sum(c - 1 for c in pairs.values() if c > 1)}")

    section("leakage: val vs train (near-duplicate = shares >= 50% of word 5-grams)")
    for src in ("casual", "coedit"):
        q = [paragraph_of(r) for r in val if source_of(r) == src]
        pool = [paragraph_of(r) for r in train]
        hits = near_duplicates(q, pool)
        print(f"  val {src}: {sum(hits)}/{len(q)} have a near-duplicate in train")

    section("leakage: evaluation sets vs training data")
    pool = [paragraph_of(r) for r in train + val]
    evals = {
        "eval_set.jsonl (40)": [c["text"] for c in load(HERE / "eval_set.jsonl")],
        "data-heldout cases": [c["text"] for c in load(HERE / "data-heldout/cases.jsonl")],
        "data-confirm cases": [c["text"] for c in load(HERE / "data-confirm/cases.jsonl")],
        "writing_eval assignments": [a["instructions"] for a in load(HERE / "writing_eval/assignments.jsonl")],
    }
    corpus = ROOT / "data/human_corpus"
    if corpus.exists():
        evals["human_corpus"] = [p.read_text(encoding="utf-8") for p in corpus.glob("*/*.txt") if not p.parent.name.startswith("_")]
    for name, texts in evals.items():
        hits = near_duplicates(texts, pool, threshold=0.3)
        print(f"  {name}: {sum(hits)}/{len(texts)} share >= 30% of 5-grams with a training paragraph")
    held = [c["text"] for c in load(HERE / "data-heldout/cases.jsonl")]
    conf = [c["text"] for c in load(HERE / "data-confirm/cases.jsonl")]
    print(f"  data-confirm vs data-heldout: {sum(near_duplicates(conf, held, threshold=0.3))}/{len(conf)} overlap")


def training_audit():
    section("training runs (trainer_state.json)")
    for run in ("out-run5", "out-run6", "out"):
        states = sorted((HERE / run / "checkpoints").glob("checkpoint-*/trainer_state.json"),
                        key=lambda p: int(p.parent.name.split("-")[1]))
        if not states:
            print(f"  {run}: no trainer_state.json")
            continue
        st = json.loads(states[-1].read_text(encoding="utf-8"))
        hist = st["log_history"]
        train_loss = [(h["step"], h["loss"]) for h in hist if "loss" in h]
        eval_loss = [(h["step"], round(h["eval_loss"], 4)) for h in hist if "eval_loss" in h]
        first, last = train_loss[0], train_loss[-1]
        tail = [l for _, l in train_loss[-5:]]
        print(f"  {run}: last checkpoint step {st['global_step']} of max_steps {st.get('max_steps')}, "
              f"epoch {round(st.get('epoch', 0), 3)}")
        print(f"    train loss step {first[0]} {first[1]:.4f} -> step {last[0]} {last[1]:.4f} "
              f"(mean of last 5 logs {sum(tail) / len(tail):.4f})")
        print(f"    eval loss (100 val examples): {eval_loss}")
        print(f"    best_model_checkpoint: {st.get('best_model_checkpoint')} (None = the final step is what was exported)")


if __name__ == "__main__":
    dataset_audit()
    training_audit()
