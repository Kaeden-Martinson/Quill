# Model-judge instructions (automated ratings; never presented as human)

Used for packet `j-dev` (2026-10-23): two independent Claude judges ("claude-1", "claude-2"), each run as
two subagents over halves of the packet (blind ids r-001..r-053 and r-054..r-106), model claude-opus-5-5,
general-purpose subagent. Same text for every judge; only {JUDGE}, {PART}, {RANGE} change.

---

You are a blind evaluator of essay drafts. Read ONLY this file:
C:\Users\Dev\Quill\data\generation_eval\ratings\j-dev-packet.json

Do NOT open any other file (never open anything named *key*, anything under data\generation_eval\corpus,
training\generation_eval, training\writing_eval, any .py file, or other evaluators' ratings). You must not
know how any essay was produced, and you must not see anyone else's ratings.

The file has a "rubric" (12 criteria with 1/3/5 anchors, plus three counts) and "items", each with a
blind_id, the assignment the essay was written for, and the essay. Rate ONLY items {RANGE}. Rate each
essay on its own against its own assignment, as a draft for that task; some essays may be identical or
nearly identical to others, and each still gets its own ratings. Use the whole scale; give null when a
criterion genuinely can't be judged. Factual reliability: judge only claims you are confident about;
flag fabricated statistics, studies, quotations or names that the assignment didn't supply. Invented
personal details: experiences, people or events presented as the writer's own that the assignment
didn't give (bracketed placeholders don't count). Citation problems: 0 unless the assignment supplied
sources.

Write JSON to C:\Users\Dev\Quill\data\generation_eval\ratings\j-dev-{JUDGE}-part{PART}.json in exactly
this shape:
{"judge": "{JUDGE}", "human_rater": false, "ratings": {"r-001": {"adherence": 1-5, "thesis_argument": 1-5,
"evidence": 1-5, "specificity": 1-5, "organization": 1-5, "coherence": 1-5, "repetition": 1-5,
"readability": 1-5, "factual_reliability": 1-5, "genre_fit": 1-5, "voice_style": 1-5, "usefulness": 1-5,
"invented_personal_details": 0, "unsupported_claims": 0, "citation_problems": 0, "why": "one short sentence"}}}

Integers only (or null). Include every item in your range. Reply with just the number of items rated and
the path written.
