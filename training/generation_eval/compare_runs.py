"""Paired comparison of a variant run with its baseline, and the decision rule fixed in followup_plans.md.

    .venv\\Scripts\\python training\\generation_eval\\compare_runs.py EXPERIMENT RATINGS VARIANT_RUN BASELINE_RUN
    e.g. compare_runs.py e2 j-e2 e2-dev baseline-dev+persuade-dev

Ratings come from a judges-runs packet (both runs rated together, blind). Differences are per sample
(variant minus baseline, each averaged over judges), with a cluster bootstrap by prompt. Writes
experiments/EXPERIMENT-result.json and prints the decision: adopt, not supported or inconclusive.
"""
import json
import statistics as st
import sys
from collections import defaultdict

from common import CORPUS, HERE, LOCAL, RATINGS, read_jsonl, words
import stats as S

CRITERIA = ["adherence", "thesis_argument", "evidence", "specificity", "organization", "coherence", "repetition",
            "readability", "factual_reliability", "genre_fit", "voice_style", "usefulness"]
COUNTS = ["invented_personal_details", "unsupported_claims", "citation_problems"]


def load_drafts(run):
    return {r["sample_id"]: r for part in run.split("+") for r in read_jsonl(CORPUS / part / "A.jsonl")}


def ratings_by_sample(name):
    """{run label: {sample_id: {criterion: mean over judges}}} plus {run: {sample: judges flagging invention}}."""
    key = json.loads((LOCAL / "ratings" / f"{name}-key.json").read_text(encoding="utf-8"))
    judges = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RATINGS.glob(f"{name}-*.json"))
              if not p.name.endswith("-summary.json") and json.loads(p.read_text(encoding="utf-8")).get("kind") == "model"]
    means, flags = defaultdict(dict), defaultdict(dict)
    for b, v in key.items():
        vals = [j["ratings"].get(b, {}) for j in judges]
        means[v["pipeline"]][v["id"]] = {c: st.mean(x[c] for x in vals if x.get(c) is not None)
                                         for c in CRITERIA + COUNTS if any(x.get(c) is not None for x in vals)}
        flags[v["pipeline"]][v["id"]] = sum(1 for x in vals if (x.get("invented_personal_details") or 0) > 0)
    return means, flags, len(judges)


def paired(means, var, base, criterion, prompt_of):
    clusters = defaultdict(list)
    for s, v in means[var].items():
        b = means[base].get(s)
        if b and criterion in v and criterion in b:
            clusters[prompt_of[s]].append(v[criterion] - b[criterion])
    ci = S.cluster_bootstrap(list(clusters.values()), S.mean, resamples=4000)
    return None if ci is None else {"diff": round(ci[0], 3), "ci95": [round(ci[1], 3), round(ci[2], 3)],
                                    "pairs": sum(len(c) for c in clusters.values())}


def length_stats(drafts, samples):
    by = defaultdict(list)
    under = 0
    for s in samples:
        r = drafts[s]
        if r.get("text"):
            ratio = words(r["text"]) / r["requested_words"]
            by[r["requested_length"]].append(ratio)
            under += ratio < 0.7
    return {"median_share": {k: round(st.median(v), 3) for k, v in by.items()}, "under_70pct": under}


def decide(exp, d, lengths, inv):
    """followup_plans.md, applied as written."""
    g = lambda c: (d.get(c) or {}).get("diff")  # noqa: E731
    if exp == "e2":
        vb, bb = lengths["variant"]["median_share"].get("medium"), lengths["baseline"]["median_share"].get("medium")
        guards = all(g(c) is not None and g(c) >= -0.2 for c in ("repetition", "coherence", "usefulness"))
        if vb is not None and vb >= 0.90 and lengths["variant"]["under_70pct"] <= lengths["baseline"]["under_70pct"] and guards:
            return "adopt"
        if vb is not None and abs(vb - bb) < 0.03:
            return "not supported"
        return "inconclusive"
    if exp == "e1":
        vb, bb = inv["variant"], inv["baseline"]
        guard = g("usefulness") is not None and g("usefulness") >= -0.25
        if bb and vb <= bb / 2 and guard:
            return "adopt the product idea (ask-first step proposed as its own change)"
        if bb and (bb - vb) < bb / 4:
            return "not supported"
        return "inconclusive"
    if exp == "e3":
        sp, ev = g("specificity"), g("evidence")
        guards = (g("factual_reliability") is not None and g("factual_reliability") >= -0.2
                  and (g("unsupported_claims") or 0) <= 0 and (g("invented_personal_details") or 0) <= 0
                  and g("adherence") is not None and g("adherence") >= -0.2)
        if sp is not None and ev is not None and sp >= 0.3 and ev >= 0.3 and guards:
            return "adopt"
        if sp is not None and ev is not None and abs(sp) < 0.1 and abs(ev) < 0.1:
            return "not supported"
        return "inconclusive"
    if exp == "e5":
        sp, ev = g("specificity"), g("evidence")
        guards = (g("factual_reliability") is not None and g("factual_reliability") >= -0.2
                  and g("adherence") is not None and g("adherence") >= -0.2
                  and (g("unsupported_claims") or 0) <= 0)
        if sp is not None and ev is not None and sp >= 0.3 and ev >= 0.3 and guards:
            return "adopt (optional examples-and-evidence field in the draft dialog)"
        if sp is not None and ev is not None and abs(sp) < 0.1 and abs(ev) < 0.1:
            return "not supported"
        return "inconclusive"
    if exp == "e4":
        sp, fr = g("specificity"), g("factual_reliability")
        if sp is not None and sp >= 0.5 and fr is not None and fr >= -0.3 and d.get("_variant_factual_mean", 0) >= 4.0:
            return "adopt (dev only; no literary prompts in eval)"
        if sp is not None and abs(sp) < 0.2:
            return "not supported"
        return "inconclusive"
    raise SystemExit(f"no rule for {exp}")


def main(exp, name, var, base):
    means, flags, n_judges = ratings_by_sample(name)
    drafts_v, drafts_b = load_drafts(var), load_drafts(base)
    samples = sorted(set(means[var]) & set(means[base]))
    prompt_of = {s: drafts_v[s]["prompt_id"] for s in samples}
    d = {c: paired(means, var, base, c, prompt_of) for c in CRITERIA + COUNTS}
    lengths = {"variant": length_stats(drafts_v, samples), "baseline": length_stats(drafts_b, samples)}
    inv = {"variant": sum(1 for s in samples if flags[var].get(s, 0) == n_judges),
           "baseline": sum(1 for s in samples if flags[base].get(s, 0) == n_judges), "of": len(samples)}
    fr = [means[var][s]["factual_reliability"] for s in samples if "factual_reliability" in means[var][s]]
    d["_variant_factual_mean"] = round(st.mean(fr), 3) if fr else None
    result = {"experiment": exp, "ratings": name, "variant_run": var, "baseline_run": base, "judges": n_judges,
              "samples": len(samples), "paired_differences": d, "lengths": lengths,
              "invented_details_flagged_by_all_judges": inv, "decision": decide(exp, d, lengths, inv)}
    out = HERE / "experiments" / f"{exp}-result.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:5])
