"""What kinds of change the line editor's training targets teach, split by data source and task.

Each edit (original sentence -> target sentence) is put in one primary class:
  punctuation    only punctuation or capitalization differs
  small_fix      one or two words changed, each a close spelling of the other (agreement, typos)
  contraction    a contraction is expanded ("it's" -> "it is") and little else changes
  informal       casual words removed or formalized (gonna, kinda, stuff, really...)
  synonym        one word swapped for a different word of the same role
  compress       target is 15%+ shorter, same order
  expand         target is 15%+ longer, same order
  reorder        mostly the same words in a different order
  rewrite        many words replaced: a paraphrase
plus flags that can apply to any class: rarer_words (the replacement words are rarer than the ones
they replace, by this corpus's own word counts), adds_content (new content words the source never
had), drops_content (40%+ of the source's content words gone), instruction_leftover.

    .venv\\Scripts\\python training\\audit_coedit.py [--examples N]
"""
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import writing_metrics as wm  # noqa: E402

STOP = set("""a an the and or but if so of to in on at by for with from as is are was were be been being
it its it's this that these those i me my we our you your he she they them their his her not no do
does did have has had will would can could should may might must just very really also then than
there here what which who whom when where why how all any some more most such only own same too""".split())
INFORMAL = {"gonna", "wanna", "gotta", "kinda", "sorta", "stuff", "things", "lots", "really", "pretty",
            "okay", "ok", "yeah", "guys", "kids", "huge", "awesome", "cool", "super", "totally", "basically"}
INSTRUCTION = re.compile(r"^(fix|make|improve|rewrite|remove|correct|update|simplify|paraphrase|write|use|change)\b"
                         r"|\b(this sentence|the sentence|this text|the text|grammatical errors)\b", re.I)

CATEGORY_TASK = {"grammar": "gec", "clarity": "clarity", "flow": "coherence", "concision": "simplification"}


def toks(s):
    return wm.words(s)


def content(ws):
    return [w for w in ws if w not in STOP and len(w) > 2]


def classify(src, tgt, freq):
    a, b = toks(src), toks(tgt)
    flags = []
    if [w for w in a] == [w for w in b]:
        primary = "punctuation"
    else:
        sm = SequenceMatcher(None, a, b, autojunk=False)
        ops = [op for op in sm.get_opcodes() if op[0] != "equal"]
        changed_a = [w for op in ops for w in a[op[1]:op[2]]]
        changed_b = [w for op in ops for w in b[op[3]:op[4]]]
        overlap = len(set(a) & set(b)) / max(1, len(set(a) | set(b)))
        contr_a, contr_b = len(wm.CONTRACTION.findall(src)), len(wm.CONTRACTION.findall(tgt))
        close = all(SequenceMatcher(None, x, y).ratio() >= 0.6 for x, y in zip(changed_a, changed_b))
        if contr_b < contr_a and len(changed_b) <= 3 * (contr_a - contr_b) + 1:
            primary = "contraction"
        elif any(w in INFORMAL for w in changed_a) and not any(w in INFORMAL for w in changed_b):
            primary = "informal"
        elif len(changed_a) <= 2 and len(changed_a) == len(changed_b) and close:
            primary = "small_fix"
        elif len(changed_a) == 1 and len(changed_b) == 1:
            primary = "synonym"
        elif sm.ratio() < 0.6 and overlap >= 0.7:
            primary = "reorder"
        elif sm.ratio() < 0.6:
            primary = "rewrite"
        elif len(b) <= 0.85 * len(a):
            primary = "compress"
        elif len(b) >= 1.15 * len(a):
            primary = "expand"
        else:
            primary = "rewrite" if len(changed_a) > 4 else "small_fix" if close else "synonym"
        # Replacement words rarer than what they replace (lower count in this corpus).
        ca, cb = content(changed_a), content(changed_b)
        if ca and cb and sum(freq[w] for w in cb) / len(cb) < 0.5 * sum(freq[w] for w in ca) / len(ca):
            flags.append("rarer_words")
        new = [w for w in content(b) if w not in set(a) and not any(SequenceMatcher(None, w, x).ratio() > 0.75 for x in a)]
        if len(new) >= 2:
            flags.append("adds_content")
        src_content = set(content(a))
        if src_content and len(src_content - set(b)) / len(src_content) >= 0.4:
            flags.append("drops_content")
    if INSTRUCTION.search(src):
        flags.append("instruction_leftover")
    return primary, flags


def main(examples=0):
    rows = [json.loads(line) for line in open(HERE / "data" / "train.jsonl", encoding="utf-8")]
    edits = []
    for r in rows:
        source = "coedit" if "No writing samples yet" in r["messages"][1]["content"] else "casual"
        for s in json.loads(r["messages"][2]["content"])["suggestions"]:
            edits.append((source, CATEGORY_TASK.get(s["category"], s["category"]), s["original"], s["revised"]))
    freq = Counter(w for _, _, src, tgt in edits for w in toks(src) + toks(tgt))

    by = defaultdict(Counter)
    flags_by = defaultdict(Counter)
    samples = defaultdict(list)
    for source, task, src, tgt in edits:
        primary, flags = classify(src, tgt, freq)
        key = source if source == "casual" else f"coedit/{task}"
        by[key][primary] += 1
        for f in flags:
            flags_by[key][f] += 1
            if len(samples[(key, f)]) < examples:
                samples[(key, f)].append((src, tgt))
        if len(samples[(key, primary)]) < examples:
            samples[(key, primary)].append((src, tgt))

    classes = ["punctuation", "small_fix", "contraction", "informal", "synonym", "compress", "expand", "reorder", "rewrite"]
    flags = ["rarer_words", "adds_content", "drops_content", "instruction_leftover"]
    print("share of each source's edits by primary class (%)")
    print("  " + "source".ljust(22) + "n".rjust(7) + "".join(c[:9].rjust(10) for c in classes))
    for key in sorted(by):
        n = sum(by[key].values())
        print("  " + key.ljust(22) + str(n).rjust(7) + "".join(f"{100 * by[key][c] / n:9.1f}%" for c in classes))
    print("\nflags (% of that source's edits)")
    print("  " + "source".ljust(22) + "".join(f.rjust(22) for f in flags))
    for key in sorted(by):
        n = sum(by[key].values())
        print("  " + key.ljust(22) + "".join(f"{100 * flags_by[key][f] / n:21.1f}%" for f in flags))

    # Same source sentence trained toward different targets: inconsistent objectives.
    targets = defaultdict(set)
    for _, _, src, tgt in edits:
        targets[src].add(tgt)
    conflicting = {s: t for s, t in targets.items() if len(t) > 1}
    pairs = Counter((src, tgt) for _, _, src, tgt in edits)
    print(f"\n{len(edits)} edits; exact duplicate (source, target) pairs: {sum(c - 1 for c in pairs.values() if c > 1)}; "
          f"source sentences with 2+ different targets: {len(conflicting)}")
    for s, t in list(conflicting.items())[:3]:
        print(f"    {s[:70]!r} -> {[x[:50] for x in t]}")

    if examples:
        for (key, label), items in sorted(samples.items()):
            if key.startswith("coedit") and label in ("rewrite", "synonym", "contraction", "adds_content", "drops_content", "rarer_words", "instruction_leftover"):
                print(f"\n  {key} / {label}:")
                for src, tgt in items:
                    print(f"    - {src[:110]}\n      > {tgt[:110]}")


if __name__ == "__main__":
    main(int(sys.argv[sys.argv.index("--examples") + 1]) if "--examples" in sys.argv else 0)
