"""Blind quality ratings: sheets for people, packets for model judges, import and aggregation (plan.md 6).

    .venv\\Scripts\\python training\\generation_eval\\ratings.py people RUN NAME [--drafts 36] [--human 12]
    .venv\\Scripts\\python training\\generation_eval\\ratings.py judges RUN NAME
    .venv\\Scripts\\python training\\generation_eval\\ratings.py import NAME FILE.csv RATER person|model
    .venv\\Scripts\\python training\\generation_eval\\ratings.py aggregate NAME

people: a stratified, seeded subset of RUN's drafts (distinct samples, half shown from pipeline A and
half from B, spread across genres) plus matched human essays as anchors, under blind ids r-001...
in a random order. judges: every A and B draft of RUN for two model judges. The key (blind id ->
pipeline, sample or human id, prompt) and the sheets live in data/generation_eval/ratings (local:
they quote licensed essays, and raters must not see the key). Imported ratings go to
training/generation_eval/ratings/NAME-RATER.json, marked person or model; aggregate reports them
separately, with missing cells counted and never filled in.
"""
import csv
import json
import random
import sys
from collections import defaultdict

from common import CORPUS, HERE, LOCAL, RATINGS, read_jsonl
import human as H
import prompts as P
import stats as S

CRITERIA = ["adherence", "thesis_argument", "evidence", "specificity", "organization", "coherence",
            "repetition", "readability", "factual_reliability", "genre_fit", "voice_style", "usefulness"]
COUNTS = ["invented_personal_details", "unsupported_claims", "citation_problems"]
SHEETS = LOCAL / "ratings"
SEED = 20261025


def prompts_by_id():
    return {p["id"]: p for split in ("dev", "eval") for p in P.load(split)}


def assignment_text(p):
    lines = [f"Assignment ({p['goal']}, for {p['audience']}, length: {p.get('length', 'medium')}):", p["instructions"]]
    return "\n".join(lines)


def items_for_people(run, n_drafts, n_human):
    rng = random.Random(SEED)
    a = {r["sample_id"]: r for r in read_jsonl(CORPUS / run / "A.jsonl") if r["text"]}
    b = {r["sample_id"]: r for r in read_jsonl(CORPUS / run / "B.jsonl")} if (CORPUS / run / "B.jsonl").exists() else {}
    by_genre = defaultdict(list)
    for sid in sorted(a):
        by_genre[a[sid]["genre"]].append(sid)
    for g in by_genre:
        rng.shuffle(by_genre[g])
    picked = []
    while len(picked) < n_drafts and any(by_genre.values()):   # round-robin over genres
        for g in sorted(by_genre):
            if by_genre[g] and len(picked) < n_drafts:
                picked.append(by_genre[g].pop())
    split = next(iter(a.values()))["split"]
    items = []
    for i, sid in enumerate(picked):
        pipeline = "B" if (i % 2 and sid in b) else "A"
        row = b[sid] if pipeline == "B" else a[sid]
        items.append({"pipeline": pipeline, "id": sid, "prompt_id": row["prompt_id"], "text": row["text"]})
    humans = [h for h in H.load(split, tiers=("A",))]
    rng.shuffle(humans)
    for h in humans[:n_human]:
        items.append({"pipeline": "human", "id": h["human_id"], "prompt_id": h.get("topic"), "text": h["text"],
                      "assignment": f"Assignment: {h['genre']} on \"{h['topic']}\" (grade {h.get('grade')})"})
    return items


def blind(items, name):
    rng = random.Random(SEED + 1)
    rng.shuffle(items)
    ps = prompts_by_id()
    key, shown = {}, []
    for n, it in enumerate(items, 1):
        bid = f"r-{n:03d}"
        key[bid] = {k: it[k] for k in ("pipeline", "id", "prompt_id")}
        text = it.get("assignment") or (assignment_text(ps[it["prompt_id"]]) if it["prompt_id"] in ps else "")
        shown.append({"blind_id": bid, "assignment": text, "essay": it["text"]})
    SHEETS.mkdir(parents=True, exist_ok=True)
    (SHEETS / f"{name}-key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    return shown


def people(run, name, n_drafts=36, n_human=12):
    shown = blind(items_for_people(run, n_drafts, n_human), name)
    rubric = (HERE / "rubric.md").read_text(encoding="utf-8")
    md = [rubric, ""]
    with open(SHEETS / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["blind_id"] + CRITERIA + COUNTS + ["notes"])
        for s in shown:
            md += [f"## {s['blind_id']}", "", s["assignment"], "", s["essay"], ""]
            w.writerow([s["blind_id"]] + [""] * (len(CRITERIA) + len(COUNTS) + 1))
    (SHEETS / f"{name}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {SHEETS / name}.md/.csv ({len(shown)} essays) and the key beside them (don't send the key)")


def judges(run, name):
    items = [{"pipeline": p, "id": r["sample_id"], "prompt_id": r["prompt_id"], "text": r["text"]}
             for p in ("A", "B") if (CORPUS / run / f"{p}.jsonl").exists()
             for r in read_jsonl(CORPUS / run / f"{p}.jsonl") if r["text"]]
    shown = blind(items, name)
    (SHEETS / f"{name}-packet.json").write_text(json.dumps({
        "rubric": (HERE / "rubric.md").read_text(encoding="utf-8"), "criteria": CRITERIA, "counts": COUNTS,
        "items": shown}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {SHEETS / name}-packet.json ({len(shown)} essays)")


def import_ratings(name, path, rater, kind):
    out = {"rater": rater, "kind": kind, "human_rater": kind == "person", "ratings": {}}
    if str(path).endswith(".json"):   # a model judge's JSON: {"ratings": {blind_id: {criterion: n}}}
        out["ratings"] = json.loads(open(path, encoding="utf-8").read())["ratings"]
    else:
        for r in csv.DictReader(open(path, encoding="utf-8-sig", newline="")):
            vals = {}
            for c in CRITERIA + COUNTS:
                v = (r.get(c) or "").strip()
                vals[c] = int(v) if v.isdigit() else None
            out["ratings"][r["blind_id"]] = vals
    key = json.loads((SHEETS / f"{name}-key.json").read_text(encoding="utf-8"))
    unknown = sorted(set(out["ratings"]) - set(key))
    if unknown:
        raise SystemExit(f"blind ids not in {name}'s key: {unknown[:10]}")
    for bid, vals in out["ratings"].items():
        for c in CRITERIA:
            if vals.get(c) is not None and not 1 <= vals[c] <= 5:
                raise SystemExit(f"{bid} {c}: {vals[c]} is outside 1-5")
    RATINGS.mkdir(exist_ok=True)
    (RATINGS / f"{name}-{rater}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"imported {len(out['ratings'])} essays from {rater} ({kind})")


def aggregate(name):
    key = json.loads((SHEETS / f"{name}-key.json").read_text(encoding="utf-8"))
    files = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RATINGS.glob(f"{name}-*.json"))]
    report = {}
    for kind in ("person", "model"):
        raters = [f for f in files if f["kind"] == kind]
        if not raters:
            continue
        section = {"raters": [r["rater"] for r in raters], "coverage": {}, "by_pipeline": {}, "alpha": {}}
        for r in raters:
            cells = [r["ratings"].get(b, {}).get(c) for b in key for c in CRITERIA]
            section["coverage"][r["rater"]] = {"cells": len(cells), "missing": sum(v is None for v in cells)}
        for pipeline in sorted({v["pipeline"] for v in key.values()}):
            ids = [b for b, v in key.items() if v["pipeline"] == pipeline]
            out = {}
            for c in CRITERIA + COUNTS:
                clusters = defaultdict(list)   # per prompt, ratings averaged over raters per essay
                for b in ids:
                    vals = [r["ratings"].get(b, {}).get(c) for r in raters]
                    vals = [v for v in vals if v is not None]
                    if vals:
                        clusters[key[b]["prompt_id"]].append(sum(vals) / len(vals))
                ci = S.cluster_bootstrap(list(clusters.values()), S.mean, resamples=2000)
                out[c] = None if ci is None else {"mean": round(ci[0], 3), "ci95": [round(ci[1], 3), round(ci[2], 3)],
                                                   "essays": sum(len(v) for v in clusters.values())}
            section["by_pipeline"][pipeline] = out
        if len(raters) >= 2:
            for c in CRITERIA:
                a = S.krippendorff_alpha([[r["ratings"].get(b, {}).get(c) for r in raters] for b in key])
                section["alpha"][c] = None if a is None else round(a, 3)
        report[kind] = section
    RATINGS.mkdir(exist_ok=True)
    (RATINGS / f"{name}-summary.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "people":
        args = sys.argv[2:]
        n_d = int(args[args.index("--drafts") + 1]) if "--drafts" in args else 36
        n_h = int(args[args.index("--human") + 1]) if "--human" in args else 12
        people(args[0], args[1], n_d, n_h)
    elif cmd == "judges":
        judges(sys.argv[2], sys.argv[3])
    elif cmd == "import":
        import_ratings(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        aggregate(sys.argv[2])
