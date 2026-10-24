"""Detector results: ingestion and validation (plan.md section 7). Scoring is done elsewhere (by you, or by
a local detector once approved); this only reads results in, checks them and keeps every gap visible.

    .venv\\Scripts\\python training\\generation_eval\\detectors.py ingest DETECTOR FILE.csv
    .venv\\Scripts\\python training\\generation_eval\\detectors.py summary

FILE.csv columns: id, group, score, label, error. id is a sample_id (groups quill-A, quill-B) or a
human_id (groups human, human-C); score is the number the detector reported (blank if none); label is
ai, human or mixed when the detector gives one (blank otherwise); error is any message instead of a
result. The detector must first be described in detectors.json, and each group must be in its
allowed_groups (a group whose texts may not go to that detector under its terms or the source's
license is refused). Rows for unknown ids, duplicates, bad labels and out-of-range scores stop the
ingest; ids with no row at all are recorded as missing.
"""
import csv
import json
import sys
import time

from common import CORPUS, DETECT, HERE, read_jsonl, sha256_file, write_jsonl
import human as H

GROUPS = ("quill-A", "quill-B", "human", "human-C")
LABELS = ("ai", "human", "mixed", "")


def registry():
    return json.loads((HERE / "detectors.json").read_text(encoding="utf-8"))["detectors"]


def known_ids():
    """Every id a detector result may refer to, by group."""
    ids = {g: set() for g in GROUPS}
    for run in CORPUS.glob("*"):
        for pipeline in ("A", "B"):
            path = run / f"{pipeline}.jsonl"
            if path.exists():
                ids[f"quill-{pipeline}"] |= {r["sample_id"] for r in read_jsonl(path) if r.get("text")}
    for r in H.load():
        ids["human"].add(r["human_id"])
    for path in H.HUMAN.glob("*-C.jsonl"):
        ids["human-C"] |= {r["human_id"] for r in read_jsonl(path)}
    return ids


def ingest(name, path):
    reg = registry()
    if name not in reg:
        raise SystemExit(f"Describe {name} in detectors.json first (name, version, score meaning, threshold, terms).")
    det = reg[name]
    ids = known_ids()
    rows, problems, seen = [], [], set()
    lo, hi = det.get("score_range") or (None, None)
    for n, r in enumerate(csv.DictReader(open(path, encoding="utf-8-sig", newline="")), 2):
        key = (r["id"], r["group"])
        if r["group"] not in GROUPS:
            problems.append(f"line {n}: unknown group {r['group']!r}")
        elif r["group"] not in det["allowed_groups"]:
            problems.append(f"line {n}: group {r['group']} not allowed for {name} (detectors.json allowed_groups)")
        elif r["id"] not in ids[r["group"]]:
            problems.append(f"line {n}: id {r['id']!r} isn't in group {r['group']}")
        if key in seen:
            problems.append(f"line {n}: duplicate result for {key}")
        seen.add(key)
        label = r.get("label", "").strip().lower()
        if label not in LABELS:
            problems.append(f"line {n}: label {label!r} isn't ai, human, mixed or blank")
        score = None
        if r.get("score", "").strip():
            try:
                score = float(r["score"])
            except ValueError:
                problems.append(f"line {n}: score {r['score']!r} isn't a number")
            if score is not None and lo is not None and not lo <= score <= hi:
                problems.append(f"line {n}: score {score} outside {lo}-{hi}")
        error = r.get("error", "").strip() or None
        if score is None and not label and not error:
            error = "no result given"
        rows.append({"detector": name, "version": det.get("version"), "id": r["id"], "group": r["group"],
                     "score": score, "label": label or None, "error": error})
    if problems:
        raise SystemExit("Not ingested:\n  " + "\n  ".join(problems[:50]))
    missing = {g: sorted(ids[g] - {r["id"] for r in rows if r["group"] == g})
               for g in det["allowed_groups"] if g in ids}
    out = DETECT / f"{name}.jsonl"
    write_jsonl(out, rows)
    (DETECT / f"{name}-ingest.json").write_text(json.dumps({
        "ingested": time.strftime("%Y-%m-%d %H:%M:%S"), "source_file_sha256": sha256_file(path),
        "rows": len(rows), "errors": sum(1 for r in rows if r["error"]),
        "missing": {g: len(v) for g, v in missing.items()}, "missing_ids": missing,
        "output_sha256": sha256_file(out)}, indent=1), encoding="utf-8")
    print(f"{name}: {len(rows)} results, {sum(1 for r in rows if r['error'])} errors, "
          f"missing {', '.join(f'{g} {len(v)}' for g, v in missing.items())}")


def load():
    """All ingested results: {detector: [rows]}."""
    return {p.stem: read_jsonl(p) for p in sorted(DETECT.glob("*.jsonl"))} if DETECT.exists() else {}


def summary():
    reg = registry()
    results = load()
    if not reg:
        print("  no detectors described in detectors.json yet")
    for name in reg:
        print(f"  {name}: {len(results.get(name, []))} results ingested")


if __name__ == "__main__":
    if sys.argv[1] == "ingest":
        ingest(sys.argv[2], sys.argv[3])
    else:
        summary()
