"""Blind quality judging for the writing experiment.

    python training\\judge_packets.py make     # writes blinded packets + a separate key
    python training\\judge_packets.py score    # unblinds judgments and summarizes per configuration

For each assignment, the drafts from every draft configuration are shuffled under the labels
A/B/C with a fixed seed; for each eval paragraph, the edited versions are shuffled the same way.
Judges (a person, or a model that didn't write the outputs) see only the packet; the key that maps
labels to configurations lives in a separate file. Judgments go in writing_eval/judgments/*.json
as {"drafts": [{"item": ..., "ratings": {"A": {...}}, "rank": ["B", "A", "C"]}], "revisions": [...]}.
"""
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE / "writing_eval"
RUNS = EVAL / "runs"
PACKETS = EVAL / "packets"
JUDGMENTS = EVAL / "judgments"
DRAFT_NAMES = ["original", "prompt-only", "improved"]
REVISE_NAMES = ["original", "v2-proofread", "v2-clarity"]

DRAFT_RUBRIC = """Rate each draft 1-5 on each criterion (5 best), then rank the drafts best to worst.
- adherence: does what the instructions and purpose ask, for that reader, using the writer's points
- honesty: no invented statistics, dates, studies, quotes, names, or experiences of the writer;
  bracketed placeholders where only the writer could supply a detail count in its favour
- development: reasoning, specificity, and use of the writer's evidence; claims are earned, not asserted
- coherence: easy to follow, ideas connect, paragraphs each do a job
- voice_fit: matches the requested voice; if none was requested, plain natural language with no invented persona
- shaped: structure and openings/endings fit this particular piece (1 = generic template, 5 = shaped to its purpose)
Also list any specific claim that looks invented or wrong under "suspect"."""

REVISE_RUBRIC = """Each version is the same original paragraph after an editor's changes. For each version give:
- meaning_kept: true if the paragraph still says what the writer meant (no added or lost claims)
- errors_fixed: 1-5, how well real errors (grammar, spelling, wrong words) were fixed (5 = all, or none needed)
- unnecessary_changes: how many changes were not needed (rewording correct, clear text)
- voice_kept: 1-5, how well the writer's own wording, register and personality survive
Then rank the versions best to worst as edits of this writer's paragraph."""


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def make(part="all"):
    """part: "drafts", "revisions" or "all". Each part keeps its own fixed shuffle, and the key
    file keeps whatever part wasn't remade."""
    PACKETS.mkdir(parents=True, exist_ok=True)
    key_path = EVAL / "judge_key.json"
    key = json.loads(key_path.read_text(encoding="utf-8")) if key_path.exists() else {"drafts": {}, "revisions": {}}
    if part in ("drafts", "all"):
        make_drafts(key)
    if part in ("revisions", "all"):
        make_revisions(key)
    key_path.write_text(json.dumps(key, indent=1), encoding="utf-8")


def make_drafts(key):
    rng = random.Random(20261022)
    key["drafts"] = {}
    assignments = {a["id"]: a for a in load(EVAL / "assignments.jsonl")}

    runs = {n: {(r["id"], r["voice"]): r for r in load(RUNS / f"draft-{n}.jsonl")} for n in DRAFT_NAMES}
    items = []
    for item in runs[DRAFT_NAMES[0]]:
        names = DRAFT_NAMES[:]
        rng.shuffle(names)
        labels = dict(zip("ABC", names))
        a = assignments[item[0]]
        voice = item[1] if item[1] != "none" else "none requested"
        items.append({"item": f"{item[0]}|{item[1]}", "assignment": a["instructions"], "purpose": a["goal"],
                      "reader": a["audience"], "requested_voice": voice,
                      "drafts": {lab: runs[n][item]["text"] or "(no draft returned)" for lab, n in labels.items()}})
        key["drafts"][f"{item[0]}|{item[1]}"] = labels
    for i in range(0, len(items), 8):  # 8 assignments per packet keeps each judging session manageable
        (PACKETS / f"drafts-{i // 8 + 1}.json").write_text(
            json.dumps({"rubric": DRAFT_RUBRIC, "items": items[i:i + 8]}, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"{len(items)} draft items in {len(range(0, len(items), 8))} packets")


def make_revisions(key):
    rng = random.Random(20261023)
    key["revisions"] = {}
    revs = {n: {r["id"]: r for r in load(RUNS / f"revise-{n}.jsonl")} for n in REVISE_NAMES}
    ritems = []
    for pid, base in revs[REVISE_NAMES[0]].items():
        names = REVISE_NAMES[:]
        rng.shuffle(names)
        labels = dict(zip("ABC", names))
        ritems.append({"item": pid, "original": base["before"],
                       "versions": {lab: revs[n][pid]["after"] for lab, n in labels.items()}})
        key["revisions"][pid] = labels
    (PACKETS / "revisions.json").write_text(
        json.dumps({"rubric": REVISE_RUBRIC, "items": ritems}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(ritems)} revision items")


HUMAN_RUBRIC = """Each item is a human-written passage and, for two editors (A and B), the list of changes each one
made to it. Judge every change on its own:
- verdict: "fix" (corrects a real error), "clarifies" (a real improvement in clarity, minimal),
  "unnecessary" (rewords correct, clear text), or "harmful" (introduces an error or changes meaning)
- meaning_kept: true if the writer's meaning survives the change
- voice_kept: true if the writer's wording and register survive (no formalizing, no fancier synonyms)
An editor with no changes gets an empty list; say whether that was right ("missed": real errors it left)."""


def make_human(edit_names=("original", "v2-clarity")):
    """Blinded packet of the editors' changes to the human-written corpus."""
    rng = random.Random(20261024)
    runs = {n: {r["id"]: r for r in load(RUNS / f"human+{n}.jsonl")} for n in edit_names}
    key_path = EVAL / "judge_key.json"
    key = json.loads(key_path.read_text(encoding="utf-8"))
    key["human"] = {}
    items = []
    for pid, base in runs[edit_names[0]].items():
        if not any(runs[n][pid]["suggestions"] for n in edit_names):
            continue  # neither editor touched it
        names = list(edit_names)
        rng.shuffle(names)
        labels = dict(zip("AB", names))
        items.append({"item": pid, "passage": base["before"],
                      "changes": {lab: [{"original": s["original"], "revised": s["revised"], "reason": s.get("reason", "")}
                                        for s in runs[n][pid]["suggestions"]] for lab, n in labels.items()}})
        key["human"][pid] = labels
    (PACKETS / "human_edits.json").write_text(json.dumps({"rubric": HUMAN_RUBRIC, "items": items}, indent=1,
                                                          ensure_ascii=False), encoding="utf-8")
    key_path.write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(items)} human passages with changes")


def score_human():
    key = json.loads((EVAL / "judge_key.json").read_text(encoding="utf-8")).get("human", {})
    tally = defaultdict(Counter)
    for path in sorted(JUDGMENTS.glob("human*.json")):
        for j in json.loads(path.read_text(encoding="utf-8")).get("human", []):
            labels = key[j["item"]]
            for lab, changes in j["changes"].items():
                name = labels[lab]
                for c in changes:
                    tally[name][c["verdict"]] += 1
                    tally[name]["meaning_lost"] += not c.get("meaning_kept", True)
                    tally[name]["voice_lost"] += not c.get("voice_kept", True)
                    tally[name]["changes"] += 1
                tally[name]["missed_errors"] += len(j.get("missed", {}).get(lab, []) or [])
    if tally:
        print("\nHUMAN-TEXT EDITS (blind verdicts per change)")
        cols = ["changes", "fix", "clarifies", "unnecessary", "harmful", "meaning_lost", "voice_lost", "missed_errors"]
        print("  " + "editor".ljust(14) + "".join(c.ljust(14) for c in cols))
        for name, t in tally.items():
            print("  " + name.ljust(14) + "".join(str(t[c]).ljust(14) for c in cols))


def score():
    key = json.loads((EVAL / "judge_key.json").read_text(encoding="utf-8"))
    draft_scores = defaultdict(lambda: defaultdict(list))
    revise_scores = defaultdict(lambda: defaultdict(list))
    suspects = defaultdict(list)
    for path in sorted(JUDGMENTS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for j in data.get("drafts", []):
            labels = key["drafts"][j["item"]]
            for lab, ratings in j["ratings"].items():
                for k, v in ratings.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        draft_scores[labels[lab]][k].append(v)
                    elif k == "suspect" and v:
                        suspects[labels[lab]] += v if isinstance(v, list) else [v]
            for pos, lab in enumerate(j.get("rank", [])):
                draft_scores[labels[lab]]["rank"].append(pos + 1)
                draft_scores[labels[lab]]["first_place"].append(1 if pos == 0 else 0)
        for j in data.get("revisions", []):
            labels = key["revisions"][j["item"]]
            for lab, ratings in j["ratings"].items():
                for k, v in ratings.items():
                    revise_scores[labels[lab]][k].append(float(v) if not isinstance(v, bool) else (1.0 if v else 0.0))
            for pos, lab in enumerate(j.get("rank", [])):
                revise_scores[labels[lab]]["rank"].append(pos + 1)

    def table(title, scores, names):
        metrics = sorted({m for n in names for m in scores[n]})
        print(f"\n{title}")
        print("  " + "criterion".ljust(22) + "".join(n.ljust(15) for n in names) + "n")
        for m in metrics:
            vals = [scores[n][m] for n in names]
            print("  " + m.ljust(22) + "".join((f"{sum(v) / len(v):.2f}" if v else "-").ljust(15) for v in vals)
                  + str(max(len(v) for v in vals)))
    if draft_scores:
        table("DRAFTS (blind ratings; rank: lower is better)", draft_scores, DRAFT_NAMES)
        for n in DRAFT_NAMES:
            if suspects[n]:
                print(f"  suspect claims in {n}: {len(suspects[n])}, e.g. {suspects[n][:4]}")
    if revise_scores:
        table("REVISIONS (blind ratings; rank: lower is better)", revise_scores, REVISE_NAMES)


if __name__ == "__main__":
    if sys.argv[1] == "make":
        part = sys.argv[2] if len(sys.argv) > 2 else "all"
        make_human() if part == "human" else make(part)
    else:
        score()
        score_human()
