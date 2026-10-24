# Model-judge instructions (automated ratings; never presented as human)

Used for packet `j-dev` (2026-10-23): two independent Claude judges ("claude-1", "claude-2"), each run as
two subagents over halves of the packet (blind ids r-001..r-053 and r-054..r-106), model claude-opus-5-5,
general-purpose subagent. Same text for every judge; only {JUDGE}, {PART}, {RANGE} change.

Also used, unchanged apart from the packet name (j-pdev) and ranges (r-001..r-070, r-071..r-140), for
packet `j-pdev` (2026-10-24): the 70 PERSUADE-prompt dev drafts from pipelines A and B.

Process notes for j-pdev, as the judges reported them:
- claude-2, part 1: a script error briefly displayed the essay text of r-071..r-087 (the other half);
  only packet text, no key; none of those items are in its output.
- claude-2, part 2: the shared scratchpad held another judge's helper script, and one command showed
  its first 300 characters, including one rating for r-054 (outside its range, rated by another agent).
  It reports its ratings were already drafted. Future judges get separate working folders.
- The two text-dependent dev prompts (A Cowboy Who Rode the Waves, Car-free cities) gave the generator
  only the article titles, because PERSUADE doesn't include the articles. Their ratings are kept but
  don't measure the generator; summaries report the five independent prompts separately.

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

## Follow-up experiment packets (2026-10-24)
`j-e2`, `j-e1`, `j-e4` (and `j-e3`, `j-eval-*` later) use the same instructions, with each subagent told to
keep any scratch files in its own folder (scratchpad\judges\<packet>-<judge>[-part]) and not to open
anything else there; packet "info" files are off limits like keys. Two packets add one sentence, applied
to the variant and its baseline alike since both are rated in the same packet:
- `j-e1`: "details the assignment does give are not invented" (the E1 variant's instructions include the
  writer's details).
- `j-e4`: "these are literary analyses, so check that scenes, events and characters' actions described
  actually happen in the work, and flag misremembered plot or invented quotations."
- `j-e1` was first built showing every essay the stored assignment, without the writer details the E1
  drafts were given, which would have made those details look invented. Its two judges were stopped
  before writing any ratings; the packet was rebuilt so each essay shows the assignment it was written
  from (ratings.judges_runs), and two new judges rated it. The first packet and key are kept under
  data/generation_eval/ratings/superseded.
