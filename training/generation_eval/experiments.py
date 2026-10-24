"""The follow-up variants in followup_plans.md, each a single change to the baseline drafting request.

    generate.py RUN dev --variant e2 [--prompts ID,ID] [--seeds 0,1,2]

e1: the writer's details for personal-experience prompts (experiments/e1_details.json) are added to the
    instructions, as if Quill had asked for them first.
e2: the length line states a range ("about 500 words (aim for 450-550)").
e3: a first call plans one concrete support per writer point; the drafting request gets that plan.
e4: literary-analysis prompts get one sentence allowing specific scenes, but no unsupplied quotations.
Variants combine with "+" (e.g. "e2+e3") only for the eval comparison of adopted changes.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
VARIANTS = ("e1", "e2", "e3", "e4")
E1_DETAILS = json.loads((HERE / "experiments" / "e1_details.json").read_text(encoding="utf-8"))["details"]
E2_RANGES = {"short": (225, 275), "medium": (450, 550), "long": (810, 990)}
E4_SENTENCE = ("Refer to specific scenes, events and characters' actions from the work; don't quote it "
               "unless the writer gave the quotation.")

E3_PLAN_SYSTEM = """You plan the support for a first draft before it is written. You don't write the draft.

For each point the writer gave (or, if they gave none, each point the piece has to make), name one
concrete example, case, step or consequence that would support it in the draft. Use only the writer's
points and widely established knowledge, stated no more precisely than you can stand behind. No
statistics, dates, studies, quotations, sources or names the writer didn't give. Never invent the
writer's experiences, feelings, people or events: where the piece needs one, say in brackets what the
writer should supply, e.g. [the moment you realized it was working].

Return 2-5 items, each a point and its support, in a sentence or two."""
E3_PLAN_SCHEMA = {
    "type": "object",
    "properties": {"plan": {"type": "array", "items": {"type": "object", "properties": {
        "point": {"type": "string"}, "support": {"type": "string"}}, "required": ["point", "support"]}}},
    "required": ["plan"],
}


def parse(variant):
    names = tuple(v for v in (variant or "baseline").split("+") if v != "baseline")
    unknown = [v for v in names if v not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variant(s) {unknown}; choose from {VARIANTS}")
    return names


def adjust_prompt_entry(p, names):
    """e1 changes the writer's input itself (the instructions), before the request is built."""
    if "e1" in names and p["id"] in E1_DETAILS:
        details = "\n".join(f"- {d}" for d in E1_DETAILS[p["id"]])
        return {**p, "instructions": p["instructions"] + "\n\nDetails I can add:\n" + details}
    return p


def adjust_user_prompt(prompt, p, names, length_text):
    """e2 and e4 change one line of the built request; nothing else in it moves."""
    if "e2" in names:
        lo, hi = E2_RANGES[p.get("length", "medium")]
        line = f"Length: {length_text}"
        assert line in prompt
        prompt = prompt.replace(line, f"{line} (aim for {lo}-{hi})", 1)
    if "e4" in names and "literary" in (p.get("goal", "") + " " + p.get("genre", "")).lower():
        line = f"Length: {length_text}"
        idx = prompt.index(line)
        end = prompt.index("\n", idx) if "\n" in prompt[idx:] else len(prompt)
        prompt = prompt[:end] + "\n\n" + E4_SENTENCE + prompt[end:]
    return prompt


def with_plan(prompt, plan):
    """e3: the drafting request plus the planned support."""
    lines = "\n".join(f"- {i.get('point', '').strip()}: {i.get('support', '').strip()}" for i in plan if isinstance(i, dict))
    return prompt + "\n\nSupport planned for this draft (use it; don't mention the plan):\n" + lines
