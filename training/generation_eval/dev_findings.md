# Dev findings: recurring weaknesses in Quill's drafts (plan.md section 9)

2026-10-24. Development data only; the eval split is untouched. Quality track only: no detector data
exists or was used. All ratings below are from two blind **model judges** (automated, not people).

**Data:** pipeline A drafts from `baseline-dev` (56 samples: 16 existing assignments and 12 new Quill-genre
prompts, two drafts each) and `persuade-dev` (50 samples from the 5 independent PERSUADE prompts; the 20
from text-dependent prompts are excluded under plan.md Amendment 1). 106 samples, 103 with text, 3
generation failures. Ollama 0.40.4, `gemma4:e4b`, live drafting prompt and settings. "Both judges" means
each judge independently gave the draft a non-zero count or the stated score.

Sample sizes are small (28 + 5 dev prompts, two judges sharing one underlying model). Frequencies are
dev estimates; nothing here is a final result.

## 1. Invented personal details

| | Count |
|---|---|
| Drafts both judges say invent personal details | 15 / 103 |
| Of these, on personal-experience prompts (narrative, application, scholarship, job, blog, personal) | 12 / 15 such drafts |
| Personal-experience drafts using a bracketed placeholder, as the prompt instructs | **0 / 15** |
| Drafts in other genres using bracketed placeholders | 28 |

- **Examples:** `a-narrative-drivers-test#s1` (judge: "the examiner and stone story are invented"),
  `a-camp-counselor#s0` ("invents babysitting scenes"), `a-blog-no-social-media#s0` ("its specifics are
  invented"), `q-personal-3#s0/#s1`.
- **Effect:** the draft presents events the writer never described as their own. For application and
  scholarship essays this is the most consequential failure: a writer who keeps the invented details is
  submitting false claims about themselves. The judges still rate these drafts as readable (usefulness
  3.0-3.75 in these genres), so readability ratings hide the problem.
- **Likely source:** model behaviour at this size. The drafting prompt already says never to invent the
  writer's experiences and to bracket what's missing; the model uses brackets in other genres but not
  where they matter most. The earlier writing investigation (REPORT.md) found every prompt variant
  invented personal details.
- **Alternatives:** the instructions give too few details to fill a 500-word personal essay, so the
  model fills the gap (the task, not the model, may be underspecified); the judges may count plausible
  elaborations of the writer's own points as invention (both judges agree on 15, so not a single judge's
  quirk, but the same model family).
- **Outside personal genres:** 3 more drafts (`a-compare-online-class#s0`,
  `p-grades-for-extracurricular-activities#s0/#s4`) add first-person experiences to arguments.

## 2. Generic substance (specificity, evidence)

| Criterion (mean of 2 judges, 103 drafts) | Mean | Drafts at 2 or below |
|---|---|---|
| Specificity | 3.04 | 11 |
| Evidence | 3.12 | 4 |
| Voice and style | 3.23 | 0 |
| Usefulness as a draft | 3.73 | 2 |

- Judges' notes use "generic" 42 times; a typical draft "covers all three points" the writer gave, "with
  little concrete support" (`q-argument-3#s0`), or has "a rebuttal, though examples are generic"
  (`a-argue-phone-ban#s1`).
- **Literary analysis is the weakest genre** (usefulness 2.5-3.4): "no textual detail or quotation"
  (`q-literary-4#s0`), "lacks specific scenes" (`q-literary-1#s0`).
- **Likely sources (hypotheses):** (a) the drafting prompt forbids "statistics, dates, studies, quotations,
  sources or names the writer didn't give", which suppresses fabrication but also the concrete detail
  that analysis needs; in literary analysis it rules out quoting the work at all. (b) The model develops
  each given point in turn rather than choosing an example first, so support stays at the level of the
  claim. (c) Model size.
- **Alternatives:** the writers' instructions are short (2-4 points), so generic support may be the
  honest result of thin input; specificity may trade off directly against the factual reliability the
  drafts score well on (4.2-4.8).

## 3. Drafts shorter than requested

| Requested | Drafts | Median share of target | Under 70% |
|---|---|---|---|
| short (~250) | 38 | 96% | 0 |
| medium (~500) | 58 | 82% | 5 |
| long (~900) | 7 | 87% | 1 |

- Shortest: `q-literary-4#s1` (91 words for 500), `a-explain-vaccines#s0` (227/500).
- Not caused by the output cap: median 942 output tokens, maximum 2,055 of 4,096; nothing truncated.
- On the 5 PERSUADE prompts, Quill's median is below the students' median on 4.
- **Likely source:** the prompt states length only as "about N words"; models at this size undershoot
  approximate targets. **Alternative:** short drafts may reflect thin instructions rather than the length
  request (the shortest are on prompts with three brief points).

## 4. Prompt compliance on style instructions (observation, no experiment proposed)

The drafting prompt asks to avoid certain filler words and patterns. In the 103 drafts: "profound" in 14,
"vital" 12, "navigate" 9, "crucial" 7, "foster" 6; "not just / not only / it's not" constructions in 58;
15 end on "In conclusion / Ultimately / Overall / In the end". These are reported only as how closely the
model follows its instructions; no experiment targets them, since changing word choice for its own sake
isn't a quality goal here (plan.md section 0).

## 5. Format leak (defect)

`a-cause-teens-work#s0`: the model emitted a stray special token inside its JSON, and the app's
post-processing kept it as a final "paragraph", so the draft ends with `]}<tool_call|>{`. 1 of 103 here;
the same text would reach a writer in the live app. Likely fix: drop paragraphs that are only
punctuation and markup in `editor.draft_stream` (an app change, so it needs your approval).

## 6. Generation failures

3 of 106 samples: one HTTP 500 during normal running (`a-lit-gatsby-light#s0`), one HTTP 500 when an
Ollama update stopped the server (`q-argument-3#s1`, documented in the run's NOTE.md), and one reply with
a title but an empty paragraph list (`q-personal-4#s0`, a personal narrative). The app shows an error for
all three.

## 7. Editor on human writing (pipeline C)

The live editor (`quill-editor-v7`, temperature 0) on the 110 dev student essays, every suggestion
applied, no goal set, Ollama 0.40.4, no errors.

| | Value |
|---|---|
| Edits applied | 1,247 (median 10 per essay, maximum 32; 1 essay unchanged) |
| Share of word and punctuation tokens changed | median 7.7%, 90th percentile 15.1%, maximum 34.7% |
| By writer group (median share changed) | ELLIPSE English learners 12.2% (40); PERSUADE non-learners 6.3% (54), learners 8.6% (6), status unknown 5.9% (10) |
| Edit categories | grammar 1,159; flow 39; clarity 21; concision 17; word choice 11 |

Student essays contain real errors, so the editor changes far more here than on published prose (about
2 words per 1,000, AUDIT.md), and most on English learners' writing. This is the input for the detector
track's question 3 (does editing change how detectors label human writing); no detector has been run.
Applying every suggestion is an upper bound; writers accept them one at a time.

Note: the run's manifest records `backend/editor.py` as hashed when the run ended, after the D1 change
(made during the run). The process loaded the earlier file at start, and D1 touches only drafting
functions, not `review_paragraph`, so the editing is unaffected.

## What these findings support

Four follow-up experiments, each changing one thing, written up in `followup_plans.md` for approval. The
detector track is separate: nothing here was chosen with detectors in mind, and no follow-up is scored
on detectors.
