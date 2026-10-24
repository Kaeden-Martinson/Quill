# Quill generator evaluation: final report

2026-10-24. Plan: `plan.md` (approved 2026-10-23; Amendment 1, 2026-10-24). Follow-ups:
`followup_plans.md`. Dev findings: `dev_findings.md`. Unless stated, quality ratings are from two
blind **model judges** (automated, not people); no human ratings have been collected. No AI detector
has been run (see section 5).

## Summary
- **The generator** is stock `gemma4:e4b` (Ollama 0.40.4) with Quill's drafting prompt; nothing is
  fine-tuned. Drafts do what the assignment asks and rarely state wrong facts, but they're generic
  (specificity and evidence about 3 of 5), come out shorter than requested (medium drafts ~82% of
  target), and **invent personal details in 12 of 15 personal-experience drafts**.
- **One change worked:** giving the drafter the writer's own details (E1) cut invented personal
  details from 12/21 to 2/21 drafts and made drafts more useful (+0.69), specific (+1.17) and better
  supported (+1.29). Quill now asks for those details before drafting personal pieces (live).
- **Three prompt changes didn't:** stating length as a range (E2: no change), planning support first
  (E3: drafts got worse on every main measure), allowing scenes in literary analysis (E4: no change).
  The live drafting prompt is unchanged.
- **One defect fixed:** model debris such as `]}<tool_call|>{` could end a draft; it's now dropped (D1).
- **Editor on student writing:** applying every suggestion changes a median 7.7% of a student essay's
  words (12.2% for English learners); whether that shifts detector labels is the detector track's open
  question.
- **Locked evaluation** (78 drafts, opened once after every dev decision): the same picture on new
  prompts: adherence 4.51, factual reliability 4.76, specificity 3.15, evidence 3.25, usefulness 3.70.
  The two genres held out of dev (compare, review) are weakest (usefulness 3.40), a sign the prompt
  doesn't generalize evenly.

## 1. Generator architecture and baseline provenance
- Model `gemma4:e4b` (Ollama digest dc35e8d9c606…, blobs sha256-370c2879…, sha256-4cb21b93…), served by
  Ollama **0.40.4** for every run (pinned: auto-update turned off; reinstalled from the verified 0.40.4
  installer after an auto-update interrupted the dev baseline, documented in that run's NOTE.md).
- Prompt `editor.DRAFT_SYSTEM` ("improved", live since 2026-10-22) and `editor.draft_prompt`;
  temperature 0.8, top_p 1.0, min_p 0.05, repeat_penalty 1.0, num_predict 4096; JSON schema
  {title, paragraphs}; post-processing `editor.draft_from_reply` (shared by app and harness).
- No retries, no automatic editor pass. The editor (`quill-editor-v7`, temperature 0) runs only when a
  writer asks for a review.
- **Original 98-100% detector results:** not in the repository and not yet provided, so they couldn't be
  traced to a configuration or reproduced.

## 2. Benchmark design and sample sizes
Two tracks (plan.md section 0): quality (primary) and detectors (false positives on human writing and
the editor's effect on them; Quill drafts only as an aggregate per detector, never broken down, and
never used to score generator variants). Dev: 33 prompts in the comparison, 106 baseline samples.
Eval: 27 prompts in the comparison, 78 drafts (plus 18 research drafts once that family is built).
Precision: 200 Tier A eval essays give about ±3 points on a 5% false-positive rate.

## 3. Prompt inventory and splits
- Quill genres: 60 topics written before generation (`topics.json`), seeded split: dev 12 new + the 16
  assignments that chose the live prompt; eval 24 including two whole held-out genres (compare,
  review); 24 reserve. Hash-locked (`prompts/lock.json`).
- PERSUADE: 15 student prompts, seeded split 7 dev / 8 eval; Amendment 1 keeps only the independent
  ones in the generator comparison (5 dev, 3 eval) because the corpus ships only the titles of the
  articles the text-dependent prompts are based on.
- Research family (writer-supplied sources): not built yet.
- The eval split was opened once, after all dev decisions (`eval_access_log.jsonl`).

## 4. Human controls
| Source | Tier | License (checked 2026-10-23) | Provenance | Dev | Eval |
|---|---|---|---|---|---|
| PERSUADE 2.0 | A | CC BY-NC-SA 4.0 | public by 2021-22 (Kaggle Feedback Prize); conditions undocumented | 70 | 200 |
| ELLIPSE | A | CC BY-NC-SA 4.0 | timed state tests, 25-30 min on computer; English learners | 40 | 100 |
| MICUSP, WAC | B | not yet confirmed | | 0 | 0 |

ELLIPSE essays also present in PERSUADE (449; 436 word for word) are excluded from ELLIPSE. Exclusions
recorded per essay. Detector use of these essays: only services whose terms say submissions aren't
retained or reused, otherwise local detectors only.

## 5. Detectors
Not run. Waiting on (a) which detectors produced the original 98-100%, on which essays, when; (b) a
choice of detectors: local open-weight ones (install needs approval) or commercial ones run by you
under their terms. Ingestion, validation and analysis are built (`detectors.py`, `report.py`), with
the aggregate-only rule for Quill drafts enforced in code.

## 6. Quality rubric and review
12 criteria scored 1-5 with written anchors plus three counts (`rubric.md`). Two model judges per
packet, blind ids, counterbalanced order, separate working folders, instructions saved
(`ratings/judge_prompt.md`, with every deviation recorded). People: sheets and import ready; none
collected.

## 7. Training-data audit
The generator isn't fine-tuned, so there is no Quill training data for it. Gemma's pretraining data
isn't disclosed; overlap with public essay corpora can't be ruled out (limitation). The editor's data
was audited separately (writing_eval/AUDIT.md).

## 8. Results
### Dev baseline (pipeline A, model judges)
| | Quill genres (53 drafts) | PERSUADE, independent (50) |
|---|---|---|
| Adherence | 4.57 | 4.78 |
| Factual reliability | 4.23 | 4.79 |
| Specificity | 3.00 | 3.08 |
| Evidence | 3.13 | 3.10 |
| Voice and style | 3.30 | 3.15 |
| Usefulness | 3.63 | 3.83 |
| Invented personal details per draft | 0.58 | 0.04 |

Generation failures: empty paragraph lists recur (1 of 106 in the baseline, 2-4 per experiment run,
mostly on personal and application prompts); one prompt (Gatsby literary analysis) produced server
errors on two seeds.

### Follow-up experiments (dev, paired, two model judges)
| | Change | Primary result | Decision |
|---|---|---|---|
| E1 | writer's details in the instructions | invented details 12/21 -> 2/21; usefulness +0.69 | adopted (product step, live) |
| E2 | length as a range | medium drafts 82.6% -> 83.5% of target | not supported |
| E3 | plan support first (two calls) | specificity -0.22, evidence -0.24, usefulness -0.28 | not adopted (worse; rule says "inconclusive") |
| E4 | scenes allowed in literary analysis | specificity +0.00 | not supported |

### Locked evaluation
Opened once, at 03:20 on 2026-10-24, after every dev decision (`eval_access_log.jsonl`). Baseline
configuration only, since no prompt change was adopted. 27 prompts, 78 samples, 75 with text (3 empty
drafts). Pipeline A, two blind model judges (Krippendorff's alpha 0.55-0.86 on every criterion):

| Criterion | Mean (95% CI) | Criterion | Mean (95% CI) |
|---|---|---|---|
| Factual reliability | 4.76 (4.58-4.88) | Readability | 3.98 (3.89-4.07) |
| Adherence | 4.51 (4.26-4.71) | Repetition (5 = none) | 3.81 (3.66-3.94) |
| Organization | 4.34 (4.11-4.52) | Usefulness | 3.70 (3.47-3.86) |
| Coherence | 4.23 (4.11-4.38) | Evidence | 3.25 (3.01-3.43) |
| Genre fit | 4.07 (3.84-4.24) | Voice and style | 3.19 (3.09-3.32) |
| Thesis and argument | 4.00 (3.82-4.13) | Specificity | 3.15 (2.92-3.36) |

Invented personal details 0.21 per draft; unsupported claims 0.01. Pipeline B (after the editor) is
within 0.1 of A on every criterion.

| Group (pipeline A) | Drafts | Adherence | Specificity | Evidence | Usefulness | Invented (both judges) |
|---|---|---|---|---|---|---|
| PERSUADE, independent | 28 | 4.64 | 3.34 | 3.50 | 3.93 | 0 |
| Other Quill genres | 24 | 4.65 | 3.08 | 3.15 | 3.77 | 1 |
| **Held-out genres** (compare, review) | 20 | 4.22 | 2.77 | 2.90 | 3.40 | 0 |
| Personal-experience | 3 | 4.17 | 4.50 | 4.00 | 3.00 | 3 |

- The dev picture holds on prompts no decision touched: faithful and factual, generic in substance.
- **Generalization:** the two genres held out of dev score lowest on usefulness, specificity and
  evidence; the live prompt was chosen on dev-style genres.
- Personal-experience drafts invented details in 3 of 3 (only 3 drafts; consistent with dev's 12/15,
  not a new estimate).
- Length: median share of target 87% (short), 86% (medium), 78% (long); 9 of 75 under 70%.

### Editor on student writing (pipeline C)
The live editor (`quill-editor-v7`, temperature 0) on student essays, every suggestion applied, no goal
set, Ollama 0.40.4, no errors:

| | Dev (110 essays) | Eval (300 essays) |
|---|---|---|
| Edits applied (median per essay) | 1,247 (10) | 3,367 (10) |
| Share of tokens changed: median / 90th pct / max | 7.7% / 15.1% / 34.7% | 6.9% / 18.8% / 40.2% |
| English learners (ELLIPSE), median changed | 12.2% | 12.2% |
| PERSUADE non-learners, median changed | 6.3% | 4.7% |
| Grammar share of edits | 93% | 94% |

The editor changes far more of student writing than of published prose, and about twice as much of
English learners' writing. This is the before/after material the detector track needs to answer
whether editing changes how detectors label human writing; no detector has been run. Applying every
suggestion is an upper bound on real use.

## 9. Reproducibility and privacy
Every draft keeps its prompt, raw reply, seed, model digests, engine version, timing and errors;
manifests hash outputs and code; runs never overwrite; outages are set aside and retried, engine changes
stop a run. Licensed essays, drafts quoting them, sheets and blind keys stay in `data/generation_eval`
(git-ignored). Nothing was uploaded anywhere. Commands: README.md.

## 10. Implementation and compute
All of plan.md section 10 is built and tested (backend 135, frontend 23 tests). Runtime on this laptop:
~35-90 s per draft, ~25-50 s per student essay through the editor; model judging ~2 minutes per
50-item packet part.

## 11. Limitations
- Model judges only (one model family); human ratings pending.
- Two judges; agreement low on some criteria (reported, not interpreted, per the plan).
- One seed per variant sample; small prompt counts for E4 (3 prompts) and personal genres (8).
- E1 tested writer details written for the experiment, a best case; real writers may give fewer.
- PERSUADE provenance conditions undocumented; Tier B controls not ingested.
- No detector results yet; the original 98-100% results unavailable.

## 12. What needs you
1. The original detector details, and which detectors to run (or approval to install local ones).
2. Human raters for the quality sheets (and the editor's `r8h` sheets).
3. Whether to build the research-essay family (choosing openly licensed sources) and Tier B controls.
4. Pushing the commits to GitHub (all committed locally; nothing pushed).
5. Turning Ollama's auto-update back on once experiments are finished.
