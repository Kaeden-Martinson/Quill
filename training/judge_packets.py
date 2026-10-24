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


def make_people_packets(source="r8", prefix="r8h", tags=("@v7", "@v8")):
    """Sheets for human raters from an existing model-judge packet, with two corrections that don't
    change any content: A/B is counterbalanced (each model shown first in half the items, shuffled
    with a fixed seed) instead of drawn independently, and versions identical to each other are
    labeled so raters rate the same text the same way. Separate prefix and key entry, so the model
    judges' packets, key and ratings stay exactly as they were."""
    rng = random.Random(20261027)
    key_path = EVAL / "judge_key.json"
    key = json.loads(key_path.read_text(encoding="utf-8"))
    old = key[source]
    key[prefix] = {"revisions": {}, "human": {}}

    def balanced(items):
        firsts = [tags[i % 2] for i in range(len(items))]
        rng.shuffle(firsts)
        return {item: ({"A": f, "B": tags[1 - tags.index(f)]}) for item, f in zip(items, firsts)}

    for kind in ("revisions", "human"):
        packet = json.loads((PACKETS / f"{source}-{kind}.json").read_text(encoding="utf-8"))
        labels = balanced([it["item"] for it in packet["items"]])
        field = "versions" if kind == "revisions" else "changes"
        for it in packet["items"]:
            by_model = {old[kind][it["item"]][lab]: value for lab, value in it[field].items()}
            it[field] = {lab: by_model[m] for lab, m in labels[it["item"]].items()}
            if kind == "revisions" and it[field]["A"] == it[field]["B"]:
                it["note"] = "Versions A and B are identical; rate them the same."
            key[prefix][kind][it["item"]] = labels[it["item"]]
        (PACKETS / f"{prefix}-{kind}.json").write_text(json.dumps(packet, indent=1, ensure_ascii=False), encoding="utf-8")
    key_path.write_text(json.dumps(key, indent=1), encoding="utf-8")
    export_for_people(prefix)


def make_models(tags=("@v7", "@v8"), prefix="r8"):
    """Blinded packets comparing editor models on the same prompt: paragraph revisions (40) and every
    change each model made to the human passages. Files: packets/<prefix>-revisions.json and
    packets/<prefix>-human.json; the key goes under "<prefix>" in judge_key.json."""
    rng = random.Random(20261026)
    key_path = EVAL / "judge_key.json"
    key = json.loads(key_path.read_text(encoding="utf-8"))
    key[prefix] = {"revisions": {}, "human": {}}
    labels_for = lambda: dict(zip("ABC", rng.sample(list(tags), len(tags))))  # noqa: E731
    if len(tags) == 3:
        # Three models: counterbalanced, so each model is A, B and C about equally often in each packet.
        # The six orders are cycled over the packet's items and shuffled with the fixed seed
        # (independent draws left one model "A" in only 6 of 40 items).
        from itertools import permutations
        pool = []

        def balanced(n):
            pool[:] = [list(permutations(tags))[i % 6] for i in range(n)]
            rng.shuffle(pool)

        labels_for = lambda: dict(zip("ABC", pool.pop()))  # noqa: E731
    revs = {t: {r["id"]: r for r in load(RUNS / f"revise-original{t}.jsonl")} for t in tags}
    ritems = []
    if len(tags) == 3:
        balanced(len(revs[tags[0]]))
    for pid, base in revs[tags[0]].items():
        labels = labels_for()
        ritems.append({"item": pid, "original": base["before"],
                       "versions": {lab: revs[t][pid]["after"] for lab, t in labels.items()}})
        key[prefix]["revisions"][pid] = labels
    (PACKETS / f"{prefix}-revisions.json").write_text(json.dumps(
        {"rubric": REVISE_RUBRIC.replace("rank the versions", f"rank the {['two', 'three'][len(tags) - 2]} versions"),
         "items": ritems},
        indent=1, ensure_ascii=False), encoding="utf-8")
    human = {t: {r["id"]: r for r in load(RUNS / f"human+original{t}.jsonl")} for t in tags}
    hitems = []
    if len(tags) == 3:
        balanced(sum(1 for pid in human[tags[0]] if any(human[t][pid]["suggestions"] for t in tags)))
    for pid, base in human[tags[0]].items():
        if not any(human[t][pid]["suggestions"] for t in tags):
            continue
        labels = labels_for()
        hitems.append({"item": pid, "passage": base["before"],
                       "changes": {lab: [{"original": s["original"], "revised": s["revised"], "reason": s.get("reason", "")}
                                         for s in human[t][pid]["suggestions"]] for lab, t in labels.items()}})
        key[prefix]["human"][pid] = labels
    rubric = HUMAN_RUBRIC if len(tags) == 2 else HUMAN_RUBRIC.replace("two editors (A and B)", "three editors (A, B and C)")
    (PACKETS / f"{prefix}-human.json").write_text(json.dumps({"rubric": rubric, "items": hitems}, indent=1,
                                                             ensure_ascii=False), encoding="utf-8")
    key_path.write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(ritems)} revision items, {len(hitems)} human passages with changes")


def export_for_people(prefix="r8"):
    """Readable sheets for human raters: a Markdown file to read and a CSV to fill in, per packet.
    Written to packets/people/ (local only, since they quote the human corpus). Labels are the same
    blind A/B as the model judges see; nothing names a model."""
    import csv
    out = PACKETS / "people"
    out.mkdir(parents=True, exist_ok=True)
    rev = json.loads((PACKETS / f"{prefix}-revisions.json").read_text(encoding="utf-8"))
    lines = [f"# Paragraph revisions ({len(rev['items'])} items)", "", rev["rubric"], ""]
    with open(out / f"{prefix}-revisions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item", "version", "meaning_kept (yes/no)", "errors_fixed (1-5)", "unnecessary_changes (count)",
                    "voice_kept (1-5)", "better version for this item (A, B or tie)", "notes"])
        for it in rev["items"]:
            lines += [f"## {it['item']}", ""] + ([f"_{it['note']}_", ""] if it.get("note") else []) \
                + ["**Original**", "", it["original"], ""]
            for lab, text in it["versions"].items():
                lines += [f"**Version {lab}**{' (same as original)' if text == it['original'] else ''}", "", text, ""]
                w.writerow([it["item"], lab, "", "", "", "", "", ""])
    (out / f"{prefix}-revisions.md").write_text("\n".join(lines), encoding="utf-8")
    hum = json.loads((PACKETS / f"{prefix}-human.json").read_text(encoding="utf-8"))
    lines = [f"# Edits to human-written passages ({len(hum['items'])} passages)", "", hum["rubric"], ""]
    with open(out / f"{prefix}-human.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item", "editor", "change #", "verdict (fix/clarifies/unnecessary/harmful)", "meaning_kept (yes/no)",
                    "voice_kept (yes/no)", "real errors this editor missed in the passage (describe; one row per editor is enough)"])
        for it in hum["items"]:
            lines += [f"## {it['item']}", "", it["passage"], ""]
            for lab, changes in it["changes"].items():
                lines += [f"**Editor {lab}**: {len(changes)} change(s)" if changes else f"**Editor {lab}**: no changes", ""]
                for n, c in enumerate(changes):
                    lines += [f"{n}. ~~{c['original']}~~", f"   → {c['revised']}", f"   _reason given: {c['reason']}_", ""]
                    w.writerow([it["item"], lab, n, "", "", "", ""])
                if not changes:
                    w.writerow([it["item"], lab, "-", "", "", "", ""])
    (out / f"{prefix}-human.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}\\{prefix}-revisions.md/.csv and {prefix}-human.md/.csv")


def import_from_people(csv_path, rater, prefix="r8"):
    """A filled-in CSV from export_for_people -> judgments/<prefix>-<kind>-<rater>.json, marked as a
    person's ratings. Blank cells stay missing (reported by coverage_and_agreement), never guessed."""
    import csv
    rows = list(csv.reader(open(csv_path, encoding="utf-8-sig")))
    head, rows = rows[0], rows[1:]
    yes = lambda v: {"yes": True, "no": False}.get(v.strip().lower())  # noqa: E731
    num = lambda v: int(v) if v.strip().isdigit() else None  # noqa: E731
    if head[0] == "item" and head[1] == "version":
        items = defaultdict(lambda: {"ratings": {}, "better": None})
        for item, lab, meaning, fixed, unnec, voice, better, *_ in rows:
            if not any(x.strip() for x in (meaning, fixed, unnec, voice)):
                continue
            items[item]["ratings"][lab] = {"meaning_kept": yes(meaning), "errors_fixed": num(fixed),
                                           "unnecessary_changes": num(unnec), "voice_kept": num(voice)}
            items[item]["better"] = items[item]["better"] or better.strip().upper() or None
        out = {"judge": rater, "human_rater": True, "revisions": [
            {"item": i, "ratings": {l: {k: v for k, v in r.items() if v is not None} for l, r in d["ratings"].items()},
             "rank": [d["better"], "B" if d["better"] == "A" else "A"] if d["better"] in ("A", "B") else []}
            for i, d in items.items()]}
        kind = "revisions"
    else:
        items = defaultdict(lambda: {"changes": defaultdict(list), "missed": defaultdict(list)})
        for item, lab, n, verdict, meaning, voice, missed, *_ in rows:
            if n != "-" and verdict.strip():
                items[item]["changes"][lab].append({"verdict": verdict.strip().lower(), "meaning_kept": yes(meaning),
                                                    "voice_kept": yes(voice)})
            if missed.strip():
                items[item]["missed"][lab].append(missed.strip())
        out = {"judge": rater, "human_rater": True, "human": [
            {"item": i, "changes": dict(d["changes"]), "missed": dict(d["missed"])} for i, d in items.items()]}
        kind = "human"
    path = JUDGMENTS / f"{prefix}-{kind}-{rater}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {path}")


def kappa(a, b):
    """Cohen's kappa for two raters' labels on the same items (None if it can't be computed)."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    labels = {x for p in pairs for x in p}
    po = sum(x == y for x, y in pairs) / len(pairs)
    pe = sum((sum(x == l for x, _ in pairs) / len(pairs)) * (sum(y == l for _, y in pairs) / len(pairs)) for l in labels)
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


def coverage_and_agreement(prefix, key):
    """Per rater file: items judged vs expected (missing ones are listed, never dropped silently); and,
    when two or more raters judged the same packet, their agreement on which version was better
    (revisions) and on each change's verdict (human passages)."""
    for kind in ("revisions", "human"):
        expected = set(key[kind])
        files = sorted(JUDGMENTS.glob(f"{prefix}-{kind}*.json"))
        choices = {}
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = {j["item"]: j for j in data.get(kind, [])}
            missing = sorted(expected - set(items))
            who = data.get("judge", path.stem)
            print(f"  {kind}: {who} ({'person' if data.get('human_rater') else 'model judge'}) judged "
                  f"{len(set(items) & expected)}/{len(expected)}" + (f"; missing {missing[:5]}..." if missing else ""))
            if kind == "revisions":
                # The preferred model per item; a tie (same rating, version texts identical) stays a tie.
                choices[who] = {i: key[kind][i][j["rank"][0]] if j.get("rank") else None for i, j in items.items()}
            else:
                choices[who] = {f"{i}#{lab}#{n}": c["verdict"] for i, j in items.items()
                                for lab, changes in j["changes"].items() for n, c in enumerate(changes)}
        raters = list(choices)
        for x in range(len(raters)):
            for y in range(x + 1, len(raters)):
                common = sorted(set(choices[raters[x]]) & set(choices[raters[y]]))
                k = kappa([choices[raters[x]][i] for i in common], [choices[raters[y]][i] for i in common])
                agree = sum(choices[raters[x]][i] == choices[raters[y]][i] for i in common)
                print(f"  {kind}: {raters[x]} vs {raters[y]}: agree on {agree}/{len(common)}, Cohen's kappa {k}")


def score_models(prefix="r8"):
    key = json.loads((EVAL / "judge_key.json").read_text(encoding="utf-8")).get(prefix)
    if not key:
        return
    print(f"\n{prefix} COVERAGE AND AGREEMENT")
    coverage_and_agreement(prefix, key)
    rev = defaultdict(lambda: defaultdict(list))
    for path in sorted(JUDGMENTS.glob(f"{prefix}-revisions*.json")):
        for j in json.loads(path.read_text(encoding="utf-8")).get("revisions", []):
            labels = key["revisions"][j["item"]]
            for lab, ratings in j["ratings"].items():
                for k, v in ratings.items():
                    rev[labels[lab]][k].append(float(v) if not isinstance(v, bool) else float(v))
            for pos, lab in enumerate(j.get("rank", [])):
                rev[labels[lab]]["rank"].append(pos + 1)
    if rev:
        print(f"\n{prefix} PARAGRAPH REVISIONS (blind)")
        for name, d in sorted(rev.items()):
            print("  " + name.ljust(8) + "  ".join(f"{k} {sum(v) / len(v):.2f}" for k, v in sorted(d.items())) + f"  (n={len(d['rank'])})")
    tally = defaultdict(Counter)
    by_source = defaultdict(Counter)  # (source, model) -> verdicts; source is the item id's prefix (sec, k8s, ...)
    for path in sorted(JUDGMENTS.glob(f"{prefix}-human*.json")):
        for j in json.loads(path.read_text(encoding="utf-8")).get("human", []):
            labels = key["human"][j["item"]]
            for lab, changes in j["changes"].items():
                t = tally[labels[lab]]
                for c in changes:
                    by_source[(j["item"].split("--")[0], labels[lab])][c["verdict"]] += 1
                    t[c["verdict"]] += 1
                    t["meaning_lost"] += not c.get("meaning_kept", True)
                    t["voice_lost"] += not c.get("voice_kept", True)
                    t["changes"] += 1
                t["missed_errors"] += len(j.get("missed", {}).get(lab, []) or [])
    if tally:
        cols = ["changes", "fix", "clarifies", "unnecessary", "harmful", "meaning_lost", "voice_lost", "missed_errors"]
        print(f"\n{prefix} HUMAN-TEXT EDITS (blind verdicts per change)")
        print("  " + "model".ljust(8) + "".join(c.ljust(14) for c in cols))
        for name, t in sorted(tally.items()):
            print("  " + name.ljust(8) + "".join(str(t[c]).ljust(14) for c in cols))
        print(f"\n{prefix} HUMAN-TEXT EDITS BY SOURCE (harmful / unnecessary, summed over judges)")
        for source in sorted({s for s, _ in by_source}):
            print("  " + source.ljust(8) + "  ".join(f"{m} {by_source[(source, m)]['harmful']}/{by_source[(source, m)]['unnecessary']}"
                                                    for m in sorted(tally)))


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
        if part == "models" and len(sys.argv) > 4:   # make models PREFIX @tag1 @tag2 [@tag3]
            make_models(tuple(sys.argv[4:]), sys.argv[3])
            sys.exit()
        {"human": make_human, "models": make_models, "people": make_people_packets}.get(part, lambda: make(part))()
    elif sys.argv[1] == "export-people":
        export_for_people()
    elif sys.argv[1] == "import-people":   # import-people FILLED.csv RATER_NAME [PREFIX, default r8h]
        import_from_people(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "r8h")
    else:
        score()
        score_models("r8h")  # people's ratings, kept apart from the model judges' (r8)
        score_human()
        score_models()
