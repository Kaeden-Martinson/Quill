# Quill generator evaluation: final report

2026-10-24. Plan: `plan.md` (approved 2026-10-23; Amendment 1, 2026-10-24). Follow-ups:
`followup_plans.md`. Dev findings: `dev_findings.md`. Unless stated, quality ratings are from two
blind **model judges** (automated, not people); no human ratings have been collected. Detectors:
three local open-weight detectors (section 5); the requested hosted ones couldn't be run.

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
- **Empty drafts now retried:** the model sometimes returns a title with no paragraphs (first-attempt
  rate 1-4% per run here, mostly personal and application pieces); since 2026-10-24 the app retries
  once before showing an error. Every run in this report predates that and counts first attempts.
- **Detectors (local, open-weight; the requested ZeroGPT, GPTZero and QuillBot are hosted services and
  weren't run):** on 300 verified pre-2022 student essays, the strongest detector here (Desklib)
  wrongly flags 5.0% as AI; Fast-DetectGPT flags 22.3%. They don't agree on which students (kappa
  -0.01). Quill's drafts are flagged 100% / 89%, a correct result.
- **The editor raises false positives on students' own essays:** with every suggestion applied
  (mostly grammar fixes, a median 7% of words), Desklib's false-positive rate goes from 5.0% to 17.3%,
  Fast-DetectGPT's from 22% to 38%; replicated on dev, not a formatting artifact. This is the most
  important risk this evaluation found for Quill's users.
- **Locked evaluation** (78 drafts, opened once after every dev decision): the same picture on new
  prompts: adherence 4.51, factual reliability 4.76, specificity 3.15, evidence 3.25, usefulness 3.70.
  The two genres held out of dev (compare, review) are weakest (usefulness 3.40), a sign the prompt
  doesn't generalize evenly.

- **Editor changes (2026-10-25, live):** suggestions are now localized (one edit per change, labelled
  typo, grammar or rewrite); "Accept all" takes typo and grammar fixes only; writers pick a mode (typos
  only / typos and grammar / everything). On 300 held-out student essays, typos mode keeps false
  positives at 9.3% (Desklib) and 10.7% (OpenAI RoBERTa), confidently under 20%; "Accept all fixes"
  17.7% / 20.0% / 29.3% (Fast-DetectGPT). The fix rate on the planted-mistake benchmarks is unchanged.
- **Generator: the writer's examples (E5, live):** an optional "Examples or evidence to use" section in
  the draft dialog; drafts given three examples were rated far better supported (+1.68) and more
  specific (+1.23).

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
**Requested:** ZeroGPT, GPTZero, QuillBot. All three are hosted services with no downloadable model;
GPTZero states it keeps a copy of submitted text, and the student corpora may only go to services that
neither retain nor reuse submissions (`sources.json`). They weren't run. As instructed, local
open-weight detectors stand in (`run_local_detectors.py`, run in the training environment, nothing
installed, nothing sent anywhere; registry with licenses and revisions in `detectors.json`):

| Detector | Kind | Decision rule (documented) |
|---|---|---|
| Desklib v1.01 (DeBERTa-v3-large) | classifier trained on RAID; reported top of the RAID leaderboard | probability >= 0.5 |
| Fast-DetectGPT, gpt-neo-2.7B pair | zero-shot (Bao et al., ICLR 2024); the authors' weakest documented pair, the one that fits 8 GB | authors' fitted probability >= 0.5 |
| OpenAI RoBERTa GPT-2 detector | dated classifier; its card warns it isn't reliable on ChatGPT-era text | "Fake" class >= 0.5 |

Scores are not calibrated probabilities of authorship (none of the three documents calibration).

**Q2. False positives on verified student essays (eval, 300 Tier A essays written before 2022):**

| Detector | Flagged as AI | 95% Wilson CI | ELLIPSE (learners) | PERSUADE |
|---|---|---|---|---|
| Desklib | 15/300 = **5.0%** | 3.1-8.1% | 4/100 | 11/200 |
| Fast-DetectGPT | 67/300 = **22.3%** | 18.0-27.4% | 22/100 | 45/200 |
| OpenAI RoBERTa | 7/300 = 2.3% | 1.1-4.7% | 2/100 | 5/200 |

Every interval lies wholly above 1%, which the plan marks "worth investigating". Dev agrees (Desklib
5.5%, Fast-DetectGPT 20.0%, OpenAI 6.4% of 110). The detectors don't agree on which essays they flag
(Fleiss' kappa -0.01; score correlations 0.04-0.10), so one detector's flag says little on its own.

**Q3. Quill's editor on the same essays (every suggestion applied, an upper bound):**

| Detector | Before editing | After editing | Flipped to AI / to human | McNemar p |
|---|---|---|---|---|
| Desklib | 5.0% | **17.3%** (13.5-22.0%) | 38 / 1 | < 1e-9 |
| Fast-DetectGPT | 22.3% | **37.7%** (32.4-43.3%) | 51 / 5 | < 1e-9 |
| OpenAI RoBERTa | 2.3% | **23.0%** (18.6-28.1%); learners 34.2% | 63 / 1 | < 1e-17 |

- Replicated on dev (Desklib 5.5% -> 21.8%).
- Not a formatting artifact: re-joining paragraphs alone leaves all 410 essays byte-identical, and
  the 7 essays the editor didn't change are identical to their originals. The edits are 93-94% grammar
  corrections.
- Even light editing flips labels: essays with under 5% of words changed were newly flagged 10-17% of
  the time; more editing goes with somewhat more flips (AUROC 0.58-0.66 for share changed).
- Per the plan this is investigated by looking at the editor's changes, never by tuning the editor
  against detectors. The finding is about risk to writers: correcting a student's grammar can make
  their own essay look machine-written to these detectors.

**Quill's drafts (aggregate only, by design):** flagged 100% (Desklib), 89% (Fast-DetectGPT), 1%
(OpenAI RoBERTa). AUROC against the student essays 0.9996, 0.93 and 0.55. AI-written drafts being
identified as AI is a correct result, consistent with the 98-100% you saw.

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
- Detectors are local open-weight stand-ins, not the hosted ZeroGPT, GPTZero or QuillBot; commercial
  detectors may behave differently. Fast-DetectGPT ran with its weakest documented model pair. The
  original 98-100% results weren't available to compare.
- The editor effect applies every suggestion (an upper bound); writers accept suggestions one at a time.

## 12. What needs you
1. **The editor finding.** Decide how Quill should respond to its editor raising detector false
   positives on students' own essays. Options that don't involve tuning against detectors: tell writers
   (a note where they accept suggestions), point them to the writing history Quill already keeps as
   evidence of authorship, and keep the writer's original version easy to export.
2. Whether to run the hosted detectors yourself on text you're free to submit (for example your own
   essays and Quill's drafts), under their terms; their results can be ingested with `detectors.py`.
3. Human raters for the quality sheets (and the editor's `r8h` sheets).
4. Whether to build the research-essay family (openly licensed sources) and Tier B controls.
5. Turning Ollama's auto-update back on once experiments are finished.

## 13. Editor and generator development (2026-10-24/25)
**Problem picked first:** the editor raising detector false positives on writers' own essays.
**Diagnosis** (`editor_diagnosis.py`, 110 dev essays, edits rebuilt by type): typo, punctuation and
capitalization fixes barely move false positives (Desklib 5.5% -> 8.2%); correcting many genuine small
grammar errors drives the rise; rewording alone doesn't. 43% of edits bundled several fixes or reworded
text, sometimes under a reason claiming no wording change.

**Changes (live):**
- `backend/localize.py`: each suggestion split into minimal pieces quoting just enough to be unique and
  unambiguous, labelled typo / grammar / rewrite, with exact descriptions for typos and honest ones for
  rewrites. Accepting every piece reproduces the model's edit exactly (0 mismatches on 610 essays).
- `/api/review` takes `mode` (typos | grammar | all, default all); a "Quill suggests" selector; "Accept
  all" takes corrections only (`isCorrection` in `frontend/text.js`); rewrites are labelled.
- Draft dialog: optional "Examples or evidence to use" (E5), beside the personal "Details only you
  know" (E1). Empty drafts are retried once; model debris is dropped (D1).

**Quality and regression results** (`editor_modes_quality.py`, the editor's planted-mistake benchmarks):

| Policy | held-out fixed / perfect / untouched / extra | confirm fixed / perfect / untouched / extra |
|---|---|---|
| everything (before) | 96.1% / 94.0% / 98.4% / 0.033 | 93.1% / 94.7% / 98.4% / 0.020 |
| accept-all fixes (now) | 96.1% / 94.7% / 100.0% / 0.027 | 93.1% / 94.7% / 98.4% / 0.020 |
| typos mode | 92.2% / 94.0% / 100.0% / 0.007 | 84.2% / 91.3% / 100.0% / 0.000 |

**Detector side effects, baseline vs final** (false-positive rate on real student essays; held-out
editor set, 300 essays, opened once; full table and dev numbers in `editor_plan.md`):

| Detector | Unedited | Before (every suggestion) | Now: Accept all fixes | Now: typos mode | Target < 20% after editing |
|---|---|---|---|---|---|
| Desklib | 4.7% | 20.0% | 17.7% [13.8-22.4] | 9.3% [6.5-13.2] | met (typos, confidently); accept-all point estimate only |
| OpenAI RoBERTa | 4.0% | 21.0% | 20.0% [15.9-24.9] | 10.7% [7.7-14.7] | met (typos, confidently); accept-all not met |
| Fast-DetectGPT | 17.0% | 32.0% | 29.3% [24.5-34.7] | 20.3% [16.2-25.2] | not met (detector flags 17% of unedited essays) |

Generated drafts are reported separately (section 5): flagged 100% / 89% / 1% before editing; the
editor barely changes them (6-19 edits per run). Generator variants were judged on quality only and
never detector-scored.

**Generator follow-ups:** E1 adopted (writer's details; invented details 12/21 -> 2/21), E2 and E4 not
supported, E3 worse, E5 adopted (writer's examples; evidence +1.68, specificity +1.23, usefulness +0.57).

**Reproduce** (from the repository root; detectors in `.venv-train`, set `QUILL_GEN_UNSEAL=1` for
held-out sets):
- `.venv\Scripts\python training\generation_eval\editor_sets.py build`
- `.venv\Scripts\python training\generation_eval\edit.py editor-set editor-dev` (and `editor-holdout`)
- `.venv-train\Scripts\python training\generation_eval\editor_diagnosis.py dev --detector NAME`
- `.venv-train\Scripts\python training\generation_eval\editor_policies.py editor-dev --detector NAME`
- `.venv\Scripts\python training\generation_eval\editor_modes_quality.py`
- `.venv\Scripts\python training\generation_eval\generate.py e5-dev dev --variant e5 --prompts ... --seeds 0,1,2`,
  then `ratings.py judges-runs`, the two judges, and `compare_runs.py e5 j-e5 e5-dev baseline-dev+e5-base-dev`
- Tests: `.venv\Scripts\python -m pytest` (154) and `node --test "tests/frontend/*.test.cjs"` (24)

**Limitations:** model judges only, no human ratings; local open-weight detectors stand in for the
hosted ones; "everything" and "accept-all" are upper bounds on what writers apply; the held-out editor
set was opened once per detector process (three log lines, one session); the editor model, prompt and
settings are unchanged, so the remaining false positives come from genuine corrections.
