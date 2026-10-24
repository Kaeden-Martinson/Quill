"""Checks every file of the generator evaluation (plan.md sections 4, 5, 9).

    .venv\\Scripts\\python training\\generation_eval\\validate.py        # exit code 1 on any problem

Prompts: required fields, unique ids, split labels, no prompt in both splits, the lock. Corpus runs:
required fields, unique sample ids, prompt ids that exist, split matching the prompt's, B rows
matching A rows, the manifest's output hash. Human controls: required fields, unique ids, tier and
split labels, no source essay in both splits, MICUSP students used by the editor experiments
(data/human_corpus, data/sealed_test) kept out, and near-duplicates (5-gram Jaccard > 0.8) between
splits or between human essays and generated drafts. Detector results: ids and groups that exist.
"""
import json
import re
import sys
from itertools import combinations

from common import CORPUS, DETECT, HUMAN, LOCAL, PROMPTS, ROOT, read_jsonl, sha256_file
import prompts as P

PROMPT_FIELDS = ("id", "family", "genre", "goal", "audience", "topic", "instructions", "evidence", "constraints",
                 "voice", "length", "split")
SAMPLE_FIELDS = ("sample_id", "prompt_id", "family", "split", "pipeline", "user_prompt", "options", "seed",
                 "model", "model_digest", "ollama_version", "timestamp", "requested_words", "actual_words", "error")
HUMAN_FIELDS = ("human_id", "source", "source_id", "tier", "license", "permitted_use", "provenance_method",
                "genre", "topic", "words", "edit_history", "ai_assistance", "split", "text")
NEAR_DUP = 0.8


def shingles(text, n=5):
    toks = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(toks[i:i + n]) for i in range(max(0, len(toks) - n + 1))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def check_fields(rows, fields, label, problems):
    for r in rows:
        missing = [f for f in fields if f not in r]
        if missing:
            problems.append(f"{label}: {r.get(fields[0], '?')} lacks {missing}")


def check_unique(rows, field, label, problems):
    seen = set()
    for r in rows:
        if r[field] in seen:
            problems.append(f"{label}: duplicate {field} {r[field]}")
        seen.add(r[field])


def validate():
    problems = []
    if not P.check():
        problems.append("prompt lock: a locked prompt file changed")
    prompts = {s: P.load(s) for s in ("dev", "eval")}
    for s, rows in prompts.items():
        check_fields(rows, PROMPT_FIELDS, f"prompts/{s}", problems)
        check_unique(rows, "id", f"prompts/{s}", problems)
        problems += [f"prompts/{s}: {r['id']} labeled {r['split']}" for r in rows if r["split"] != s]
    both = {r["id"] for r in prompts["dev"]} & {r["id"] for r in prompts["eval"]}
    problems += [f"prompt in both splits: {i}" for i in sorted(both)]
    instr = {s: {r["instructions"] for r in rows} for s, rows in prompts.items()}
    problems += [f"identical instructions in dev and eval: {t[:60]}..." for t in instr["dev"] & instr["eval"]]
    split_of = {r["id"]: s for s, rows in prompts.items() for r in rows}

    drafts = []
    for run in sorted(CORPUS.glob("*")) if CORPUS.exists() else []:
        a_path = run / "A.jsonl"
        if not a_path.exists():
            continue
        a = read_jsonl(a_path)
        check_fields(a, SAMPLE_FIELDS, f"{run.name}/A", problems)
        check_unique(a, "sample_id", f"{run.name}/A", problems)
        for r in a:
            if r["prompt_id"] not in split_of:
                problems.append(f"{run.name}/A: {r['sample_id']} refers to unknown prompt {r['prompt_id']}")
            elif split_of[r["prompt_id"]] != r["split"]:
                problems.append(f"{run.name}/A: {r['sample_id']} labeled {r['split']}, prompt is {split_of[r['prompt_id']]}")
            if r.get("text"):
                drafts.append((f"{run.name}/{r['sample_id']}", r["text"]))
        manifest = run / "manifest.json"
        if manifest.exists() and json.loads(manifest.read_text(encoding="utf-8"))["A.jsonl_sha256"] != sha256_file(a_path):
            problems.append(f"{run.name}: A.jsonl changed after its manifest was written")
        b_path = run / "B.jsonl"
        if b_path.exists():
            a_ids = {r["sample_id"] for r in a if r.get("text")}
            b = read_jsonl(b_path)
            check_unique(b, "sample_id", f"{run.name}/B", problems)
            problems += [f"{run.name}/B: {r['sample_id']} has no A draft" for r in b if r["sample_id"] not in a_ids]
            problems += [f"{run.name}/B: {r['sample_id']} before-text differs from A" for r in b
                         if r["sample_id"] in a_ids and r["before"] != next(x["text"] for x in a if x["sample_id"] == r["sample_id"])]

    humans = []
    for path in sorted(HUMAN.glob("*.jsonl")) if HUMAN.exists() else []:
        if path.stem.endswith("-C"):
            continue
        rows = read_jsonl(path)
        check_fields(rows, HUMAN_FIELDS, f"human/{path.stem}", problems)
        humans += rows
    check_unique(humans, "human_id", "human", problems)
    problems += [f"human: {r['human_id']} tier {r['tier']!r}" for r in humans if r["tier"] not in ("A", "B", "C")]
    problems += [f"human: {r['human_id']} split {r['split']!r}" for r in humans if r["split"] not in ("dev", "eval")]
    for r in humans:
        if r["source"] == "micusp" and editor_micusp_student(r["source_id"]):
            problems.append(f"human: {r['human_id']} is a MICUSP student number the editor experiments use")

    sh = {f"human/{r['human_id']}": ((r["split"], r["source"]), shingles(r["text"])) for r in humans}
    sh.update({f"draft/{k}": (("draft", "quill"), shingles(t)) for k, t in drafts})
    keys = sorted(sh)
    for x, y in combinations(keys, 2):
        (sx, srcx), (sy, srcy) = sh[x][0], sh[y][0]
        both_human = x.startswith("human") and y.startswith("human")
        cross = both_human and (sx != sy or srcx != srcy)   # across splits, or the same essay in two corpora
        human_vs_draft = x.startswith("human") != y.startswith("human")
        if (cross or human_vs_draft) and jaccard(sh[x][1], sh[y][1]) > NEAR_DUP:
            problems.append(f"near-duplicate (5-gram Jaccard > {NEAR_DUP}): {x} and {y}")

    if DETECT.exists():
        import detectors as D
        ids = D.known_ids()
        for name, rows in D.load().items():
            problems += [f"detector {name}: {r['id']} not in {r['group']}" for r in rows if r["id"] not in ids.get(r["group"], ())]

    print(f"prompts: dev {len(prompts['dev'])}, eval {len(prompts['eval'])}; drafts {len(drafts)}; human {len(humans)}")
    print("\n".join(["validation: OK"] if not problems else [f"validation: {len(problems)} problem(s)"] + problems[:100]))
    return not problems


def editor_micusp_student(paper_id):
    """True for MICUSP papers (DEPT.Gx.NN.n) by student numbers the editor experiments use: 01 in
    data/human_corpus and 02-05 in the sealed editor test (training/sealed_test.py documents both).
    Decided by that rule, so the sealed test's files are never opened here."""
    m = re.match(r"[A-Z]{3}\.G\d\.(\d\d)", paper_id)
    return bool(m) and 1 <= int(m.group(1)) <= 5


if __name__ == "__main__":
    sys.exit(0 if validate() else 1)
