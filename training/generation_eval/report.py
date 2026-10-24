"""Summaries and the report for one split (plan.md sections 3, 7, 8).

    .venv\\Scripts\\python training\\generation_eval\\report.py SPLIT RUN [--ratings NAME] [--human-c NAME]

Writes training/generation_eval/report-SPLIT-RUN.md and summary-SPLIT-RUN.json from whatever exists, saying
plainly what is missing. Detector analysis, per detector:
- human essays (Tier A for Q2; Tier B separately): false-positive rate at the detector's documented
  label or threshold, Wilson and exact intervals, score quantiles, and exploratory breakdowns by
  source, genre, length band and English-learner status;
- Quill drafts (A, B): one aggregate true-positive rate each with a cluster-bootstrap interval (by
  prompt), score quantiles and AUROC against Tier A. Never broken down by genre, length, prompt or
  any text feature (plan.md section 0);
- Q3, human essays before and after Quill's editor: label flips (exact McNemar) and paired score change;
- agreement between detectors (Fleiss' kappa on labels, Spearman on scores) and missing results.
Plan rules applied as written: "worth investigating" and "inconclusive" (plan.md section 8).
"""
import json
import sys
from collections import Counter, defaultdict
from itertools import combinations

from common import CORPUS, HERE, HUMAN, RATINGS, read_jsonl, require_unsealed, words
import detectors as D
import human as H
import stats as S


def is_ai(row, det):
    """The detector's own call: its label if it gives one, else score >= its documented threshold."""
    if row.get("error"):
        return None
    if row.get("label") in ("ai", "human", "mixed"):
        return row["label"] == "ai"
    if row.get("score") is not None and det.get("threshold") is not None:
        hi_ai = det.get("higher_means", "ai") == "ai"
        return row["score"] >= det["threshold"] if hi_ai else row["score"] <= det["threshold"]
    return None


def quantiles(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    q = lambda f: xs[min(len(xs) - 1, int(f * len(xs)))]  # noqa: E731
    return {"n": len(xs), "min": xs[0], "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "max": xs[-1]}


def rate(calls):
    calls = [c for c in calls if c is not None]
    k, n = sum(calls), len(calls)
    w = S.wilson(k, n)
    cp = S.clopper_pearson(k, n)
    return None if w is None else {"flagged": k, "n": n, "rate": round(w[0], 4), "wilson95": [round(w[1], 4), round(w[2], 4)],
                                   "exact95": [round(cp[0], 4), round(cp[1], 4)]}


def length_band(n):
    return "under 300" if n < 300 else "300-600" if n <= 600 else "over 600"


def detector_section(name, det, rows, humans, drafts, human_c):
    by = defaultdict(dict)
    for r in rows:
        by[r["group"]][r["id"]] = r
    out = {"detector": name, "version": det.get("version"), "score_meaning": det.get("score_meaning"),
           "threshold": det.get("threshold"), "calibrated": det.get("calibrated", False), "missing": {}, "errors": {}}
    for tier in ("A", "B"):
        hs = [h for h in humans if h["tier"] == tier]
        res = [by["human"].get(h["human_id"]) for h in hs]
        out["missing"][f"human tier {tier}"] = sum(r is None for r in res)
        out["errors"][f"human tier {tier}"] = sum(1 for r in res if r and r["error"])
        calls = [is_ai(r, det) if r else None for r in res]
        out[f"human_tier_{tier}"] = {"false_positive": rate(calls),
                                     "scores": quantiles([r["score"] for r in res if r]), "essays": len(hs)}
        if tier == "A":
            sub = {}
            for label, keyf in (("source", lambda h: h["source"]), ("genre", lambda h: h["genre"]),
                                ("length", lambda h: length_band(h["words"])), ("english_learner", lambda h: h.get("ell") or "unknown")):
                groups = defaultdict(list)
                for h, c in zip(hs, calls):
                    groups[keyf(h)].append(c)
                sub[label] = {g: rate(cs) for g, cs in sorted(groups.items())}
            out["human_tier_A"]["exploratory_breakdowns"] = sub
    tier_a_scores = [by["human"][h["human_id"]]["score"] for h in humans
                     if h["tier"] == "A" and h["human_id"] in by["human"] and by["human"][h["human_id"]]["score"] is not None]
    for pipeline, ds in drafts.items():
        group = f"quill-{pipeline}"
        res = {d["sample_id"]: by[group].get(d["sample_id"]) for d in ds}
        out["missing"][group] = sum(r is None for r in res.values())
        out["errors"][group] = sum(1 for r in res.values() if r and r["error"])
        clusters = defaultdict(list)
        for d in ds:
            c = is_ai(res[d["sample_id"]], det) if res[d["sample_id"]] else None
            if c is not None:
                clusters[d["prompt_id"]].append(1.0 if c else 0.0)
        ci = S.cluster_bootstrap(list(clusters.values()), S.mean, resamples=2000)
        scores = [r["score"] for r in res.values() if r and r["score"] is not None]
        auc = S.auroc(scores, tier_a_scores) if det.get("higher_means", "ai") == "ai" else S.auroc(tier_a_scores, scores)
        out[group] = {"true_positive_rate": None if ci is None else {"rate": round(ci[0], 4), "cluster_bootstrap95":
                      [round(ci[1], 4), round(ci[2], 4)], "n": sum(len(v) for v in clusters.values())},
                      "scores": quantiles(scores), "auroc_vs_tier_A": None if auc is None else round(auc, 4),
                      "note": "aggregate only by design (plan.md section 0)"}
    if human_c:
        pairs = [(by["human"].get(h), by["human-C"].get(h)) for h in human_c]
        pairs = [(a, b) for a, b in pairs if a and b]
        calls = [(is_ai(a, det), is_ai(b, det)) for a, b in pairs]
        calls = [(x, y) for x, y in calls if x is not None and y is not None]
        b_flip = sum(1 for x, y in calls if not x and y)   # human -> ai after editing
        c_flip = sum(1 for x, y in calls if x and not y)
        diffs = [[b["score"] - a["score"]] for a, b in pairs if a["score"] is not None and b["score"] is not None]
        ci = S.cluster_bootstrap(diffs, S.mean, resamples=2000)
        out["editor_effect_Q3"] = {"pairs": len(calls), "became_ai": b_flip, "became_human": c_flip,
                                   "mcnemar_p": S.mcnemar_exact(b_flip, c_flip),
                                   "mean_score_change": None if ci is None else [round(v, 4) for v in ci]}
    return out


def flags(section, overall_human_rate):
    """plan.md section 8, applied as written."""
    found = []
    fp = (section.get("human_tier_A") or {}).get("false_positive")
    if fp and fp["wilson95"][0] > 0.01:
        found.append("worth investigating: Tier A false-positive interval lies wholly above 1%")
    for label, groups in ((section.get("human_tier_A") or {}).get("exploratory_breakdowns") or {}).items():
        for g, r in groups.items():
            if r and overall_human_rate and r["rate"] >= 2 * overall_human_rate:
                found.append(f"worth investigating (exploratory): {label}={g} rate {r['rate']} is at least double the overall")
    q3 = section.get("editor_effect_Q3")
    if q3 and q3["mcnemar_p"] is not None and q3["mcnemar_p"] < 0.05:
        found.append("worth investigating: the editor changes labels on human essays (McNemar p < 0.05)")
    for group, miss in section["missing"].items():
        total = (section.get(group.replace("human tier ", "human_tier_")) or {}).get("essays")
        if total and miss / total > 0.2:
            found.append(f"inconclusive: more than 20% of results missing for {group}")
    if fp and fp["wilson95"][1] - fp["wilson95"][0] > 0.15:
        found.append("inconclusive: Tier A false-positive interval wider than 15 points")
    return found


def corpus_section(run):
    out = {}
    for pipeline in ("A", "B"):
        path = CORPUS / run / f"{pipeline}.jsonl"
        if not path.exists():
            continue
        rows = read_jsonl(path)
        ok = [r for r in rows if r.get("text")]
        ratio = defaultdict(list)
        for r in ok:
            ratio[r["requested_length"]].append(words(r["text"]) / r["requested_words"])
        out[pipeline] = {"samples": len(rows), "with_text": len(ok), "errors": sum(1 for r in rows if r.get("error")),
                         "truncated": sum(1 for r in rows if r.get("truncated")),
                         "length_ratio_by_requested": {k: quantiles(v) for k, v in sorted(ratio.items())},
                         "under_70pct_of_target": sum(1 for r in ok if words(r["text"]) < 0.7 * r["requested_words"]),
                         "edits_applied": sum(len(r.get("edits_applied", [])) for r in rows) if pipeline == "B" else None}
    return out


def build(split, run, ratings_name=None, human_c_name=None):
    require_unsealed(split, f"report.py {split} {run}")
    humans = H.load(split)
    drafts = {p: [r for r in read_jsonl(CORPUS / run / f"{p}.jsonl") if r.get("text")]
              for p in ("A", "B") if (CORPUS / run / f"{p}.jsonl").exists()}
    human_c = [r["human_id"] for r in read_jsonl(HUMAN / f"{human_c_name}-C.jsonl")] if human_c_name else []
    reg, results = D.registry(), D.load()
    summary = {"split": split, "run": run, "corpus": corpus_section(run),
               "human": {"essays": len(humans), "by_source_tier": dict(Counter(f"{h['source']} (tier {h['tier']})" for h in humans))},
               "detectors": {}, "agreement": {}, "ratings": None, "flags": {}}
    for name, rows in results.items():
        if name in reg:
            sec = detector_section(name, reg[name], rows, humans, drafts, human_c)
            summary["detectors"][name] = sec
            fp = (sec.get("human_tier_A") or {}).get("false_positive")
            summary["flags"][name] = flags(sec, fp["rate"] if fp else None)
    calls = defaultdict(dict)
    scores = defaultdict(dict)
    for name, rows in results.items():
        for r in rows:
            if r["group"] == "human":
                c = is_ai(r, reg.get(name, {}))
                if c is not None:
                    calls[r["id"]][name] = c
                if r["score"] is not None:
                    scores[name][r["id"]] = r["score"]
    names = sorted(n for n in results if n in reg)
    if len(names) >= 2:
        full = [[v[n] for n in names] for v in calls.values() if all(n in v for n in names)]
        k = S.fleiss_kappa(full)
        summary["agreement"]["human_labels_fleiss_kappa"] = {"kappa": None if k is None else round(k, 3), "essays": len(full)}
        for a, b in combinations(names, 2):
            common = sorted(set(scores[a]) & set(scores[b]))
            rho = S.spearman([scores[a][i] for i in common], [scores[b][i] for i in common])
            summary["agreement"][f"spearman {a} vs {b}"] = {"rho": None if rho is None else round(rho, 3), "essays": len(common)}
    if ratings_name and (RATINGS / f"{ratings_name}-summary.json").exists():
        summary["ratings"] = json.loads((RATINGS / f"{ratings_name}-summary.json").read_text(encoding="utf-8"))
    (HERE / f"summary-{split}-{run}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (HERE / f"report-{split}-{run}.md").write_text(render(summary), encoding="utf-8")
    print(f"wrote report-{split}-{run}.md and summary-{split}-{run}.json")


def render(s):
    lines = [f"# Generator evaluation: {s['split']} split, run {s['run']}", "",
             "Generated by report.py from the files present; anything missing is listed as missing.", "", "## Corpus"]
    for p, c in s["corpus"].items():
        lines.append(f"- Pipeline {p}: {c['samples']} samples, {c['with_text']} with text, {c['errors']} errors, "
                     f"{c['truncated']} hit the output cap, {c['under_70pct_of_target']} under 70% of the requested length"
                     + (f", {c['edits_applied']} editor edits applied" if c.get("edits_applied") is not None else ""))
    if not s["corpus"]:
        lines.append("- missing: no corpus for this run")
    lines += ["", "## Human controls", f"- {s['human']['essays']} essays: {s['human']['by_source_tier'] or 'missing (none ingested)'}",
              "", "## Quality ratings"]
    if not s["ratings"]:
        lines.append("- missing: no ratings aggregated")
    else:
        for kind, sec in s["ratings"].items():
            who = "people" if kind == "person" else "model judges (automated, not people)"
            lines.append(f"### {who}: {', '.join(sec['raters'])}")
            for pipeline, crit in sec["by_pipeline"].items():
                cells = [f"{c} {v['mean']} [{v['ci95'][0]}, {v['ci95'][1]}]" for c, v in crit.items() if v]
                lines.append(f"- {pipeline}: " + "; ".join(cells))
            if sec["alpha"]:
                lines.append("- Krippendorff's alpha: " + ", ".join(f"{c} {a}" for c, a in sec["alpha"].items()))
    lines += ["", "## Detectors"]
    if not s["detectors"]:
        lines.append("- missing: no detector results ingested")
    for name, d in s["detectors"].items():
        lines += [f"### {name} (version {d['version']}; score: {d['score_meaning']}; threshold {d['threshold']}; "
                  f"calibrated: {d['calibrated']})"]
        for tier in ("A", "B"):
            fp = d[f"human_tier_{tier}"]["false_positive"]
            lines.append(f"- Human tier {tier}: " + (f"false positives {fp['flagged']}/{fp['n']} = {fp['rate']} "
                                                    f"(Wilson {fp['wilson95']}, exact {fp['exact95']})" if fp else "no usable results"))
        for p in ("quill-A", "quill-B"):
            if p in d:
                t = d[p]["true_positive_rate"]
                lines.append(f"- {p} (aggregate only): " + (f"flagged rate {t['rate']} {t['cluster_bootstrap95']} of {t['n']}; "
                                                            f"AUROC vs tier A {d[p]['auroc_vs_tier_A']}" if t else "no usable results"))
        if d.get("editor_effect_Q3"):
            q = d["editor_effect_Q3"]
            lines.append(f"- Editor effect on human essays: {q['became_ai']} became AI, {q['became_human']} became human "
                         f"of {q['pairs']}; McNemar p {q['mcnemar_p']}; mean score change {q['mean_score_change']}")
        lines.append(f"- Missing results: {d['missing']}; errors: {d['errors']}")
        for f in s["flags"].get(name, []):
            lines.append(f"- {f}")
    if s["agreement"]:
        lines += ["", "## Agreement between detectors (human essays)"] + [f"- {k}: {v}" for k, v in s["agreement"].items()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    args = sys.argv[1:]
    opt = lambda flag: args[args.index(flag) + 1] if flag in args else None  # noqa: E731
    build(args[0], args[1], opt("--ratings"), opt("--human-c"))
