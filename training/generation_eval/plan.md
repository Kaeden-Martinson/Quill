# Generator evaluation plan (draft, awaiting approval; nothing generated or scored)

Written 2026-10-23. Separate from the editor rounds (7, 8, 8a); touches none of their artifacts, the
sealed editor test, `quill-editor-v7` or the live app.

## 0. Scope and one deliberate restriction
Two tracks, kept apart:
- **Quality track (primary):** how good Quill's drafts are, where they fail, and controlled experiments
  to improve them. Judged by people (and labeled model judges), never by detectors.
- **Detector track (research):** how detectors treat verified human writing, and whether Quill's
  editor changes that. Quill drafts are AI-written; a detector flagging them is a correct result, so
  their scores are reported only as each detector's aggregate true-positive rate, the denominator the
  false-positive analysis needs.

Restriction: no analysis of which Quill drafts score lower on detectors (by genre, length, prompt,
feature or variant), and no detector scoring of generator variants in follow-up experiments. Those
analyses map how to make AI text pass as human, which this project rules out. Genre and length
breakdowns are done for human text, where they protect writers.

## 1. What is being evaluated (as found, 2026-10-23)
- Generator: stock `gemma4:e4b` via Ollama 0.40.4 (Modelfile FROM sha256-370c2879…, sha256-4cb21b93…;
  `ollama list` id dc35e8d9c606). Not fine-tuned; no Quill training data. `QUILL_OVERVIEW_MODEL`.
- Prompt: `DRAFT_SYSTEM` ("improved", live since commit 2e07a1b, 2026-10-22 22:25) plus
  `draft_prompt()`: voice ("Not given." when the writer has no samples), optional goal/audience/tone,
  length (short ~250, medium ~500, long ~900 words), the writer's instructions. JSON schema output
  {title, paragraphs}.
- Settings: temperature 0.8, top_p 1.0, min_p 0.05, repeat_penalty 1.0, num_predict 4096, no seed;
  Gemma's hidden thinking counts toward the cap.
- Post-processing: whitespace collapsed, paragraphs split on blank lines, title trimmed to 200 chars.
  No retries, no truncation besides the cap, no automatic editor pass (the editor runs only when the
  writer asks for a review; suggestions are accepted one by one).
- Dev vs live: identical model, prompt and settings; the dev harness (`compare_writing.py draft`)
  doesn't stream and has no queue.

Pipelines: **A** generator alone (what the app returns). **B** A, then the live editor
(`quill-editor-v7`, temperature 0, 800-token cap) on every paragraph with all suggestions applied: an
upper bound on editing, since writers accept selectively. **C** verified human essays through the same
editor (detector track).

## 2. Evidence already here, and what's missing
- Original 98-100% detector results: **not in the repository**. AUDIT.md section 5 records that no
  detector was run here. Unknown: which detectors, dates, which essays, which prompt version.
- Two AI drafts in the app database (one user, the owner): 2026-10-22 13:37 (old prompt) and 22:28
  (three minutes after the switch; prompt version uncertain). Not read.
- `writing_eval/runs/draft-*.jsonl`: 32 drafts each for four prompt setups on 16 assignments, with
  model-judge ratings (REPORT.md). These assignments chose the live prompt, so they're dev-only.
- `data/human_corpus`: 54 passages (MICUSP, WAC, SEC, Kubernetes) with URLs and terms; MICUSP also feeds
  the sealed editor test.

## 3. Research questions
Primary (locked evaluation set):
- **Q1 Quality.** Per-criterion ratings of pipeline A drafts on the 12-item rubric (section 6), with
  uncertainty; same for B, reported separately.
- **Q2 False positives.** For each detector, the share of Tier A human essays it labels AI at its own
  documented threshold.
- **Q3 Editor effect.** For each detector, how many Tier A human essays change label after pipeline C
  (paired), and the paired score change.

Exploratory (reported as such): false-positive rates by genre, length band, grade and English-learner
status; detector agreement; each detector's aggregate true-positive rate on A; failure modes (section 9).

Hypotheses: H1 false-positive rates differ between detectors and are higher for short texts and
English-learner writing (as published evaluations report); H2 the editor changes few labels, since it
changes about 2 words per 1,000 on human text (AUDIT.md); H3 the main quality weaknesses are invented
personal detail, generic development and length under target (REPORT.md: median 428 words for a
500-word request, minimum 119).

## 4. Prompts and splits
Families, each with genre, audience, length, required evidence and constraints recorded:
1. **PERSUADE prompts** (15 assignments that PERSUADE 2.0 students answered; argumentative,
   independent and source-based). Quill writes to the same prompt and source texts, matched to the
   students' grade level and median length. This gives exact human matching.
2. **Quill genres** in the product (argument, narrative/personal, literary analysis, explanation,
   compare/contrast, cause/effect, letter, op-ed, review, how-to, application essays, blog, position
   paper). New prompts written from a fixed template (genre × audience × topic), with topics drawn by
   seeded random sample from a written topic list, before any generation.
3. **Research-based**: the writer supplies 2-3 real, checkable sources in the instructions (the
   generator is told not to invent any); citations are verified against them.

Splits by family, never by sample: PERSUADE prompts 7 dev / 8 eval (assigned by seeded shuffle);
Quill genres: the 16 existing assignments + 12 new = dev, 24 new = eval (held-out topics and two
genres held out entirely); research prompts 4 dev / 6 eval. The eval set is hash-locked like the sealed
editor test and opened once, after development decisions.

Per sample saved: sample and prompt ids, exact system + user prompt, full output and raw JSON, model
name and blob digests, Ollama version, options, seed, timestamp, requested and actual words,
done_reason (cap hit), errors, exclusions with reasons.

Counts (eval): PERSUADE 8 prompts × 10 = 80; Quill genres 24 × 2 = 48; research 6 × 3 = 18; total 146
drafts for A, the same 146 through the editor for B. Multiple samples per prompt are analyzed with
prompt as the cluster. Production sends no seed; this harness sets a recorded seed per sample, which
fixes the draw without changing the sampling distribution.

## 5. Human controls
Provenance tiers (a dataset calling text human isn't enough):
- **Tier A**: collected before November 2022 under documented research or testing conditions.
  Candidates: PERSUADE 2.0 (grades 6-12, 15 prompts, ~25,000 essays) and ELLIPSE (English learners,
  grades 8-12, ~6,500 essays). Data licenses still to be confirmed at the download pages: the Zenodo
  records' CC BY 4.0 covers the preprints only; PERSUADE 1.0's data is CC BY-NC-SA 4.0.
- **Tier B**: pre-2022, authorship documented but not supervised: MICUSP (excluding sealed-test and
  human_corpus student ids), WAC Clearinghouse books.
- **Tier C**: anything else; excluded from Q2 and Q3.

Eval sample: PERSUADE 8 eval prompts × 25 = 200 essays; ELLIPSE 100; MICUSP 60; WAC 40. Exact-duplicate
and near-duplicate (5-gram Jaccard > 0.8) checks within and across splits. No private essays; nothing
from the app database.

## 6. Quality review
Rubric (1-5 with written anchors for 1, 3 and 5): assignment adherence, thesis and argument, evidence,
specificity, organization, coherence, repetition, readability, factual reliability, genre fit, voice
and style, overall usefulness as a draft. Plus counts: invented personal details, unsupported factual
claims, fabricated or wrong citations (checked against sources).
- People: 2-3 raters on a stratified subset of 36 eval drafts (A and B mixed, plus 12 matched human
  essays as an anchor), blind IDs, randomized order, no detector scores or model names shown. Same
  sheet and import tooling as HUMAN_REVIEW.md.
- Model judges: two Claude judges on all drafts, prompts saved, labeled automated, never merged with
  people's ratings.
- Agreement: Krippendorff's alpha (ordinal) per criterion; missing cells reported, never imputed.

## 7. Detectors
Unknown until you say which produced the 98-100%. Selection criteria: terms permit research use and
the planned inputs; version or date recordable; documented score meaning and threshold.
- Local open-weight detectors (e.g. Fast-DetectGPT, Binoculars): nothing leaves the machine, so
  licensed corpora can be scored. Needs package installs and model downloads (several GB; Binoculars'
  two 7B models may not fit 8 GB of VRAM).
- Commercial detectors: run by you under their terms; only text whose license and the service's
  data-retention terms allow submission. Quill drafts and your own text are fine; licensed student
  corpora probably aren't without permission. I don't submit text to external services.
Per detector: name, version/date, length limits, score meaning, threshold, terms, errors and missing
results. Same procedure for every group. Scores are not read as probabilities unless the vendor
documents calibration.

## 8. Statistics
- Rates: Wilson 95% intervals; Clopper-Pearson upper bound when zero are flagged (about 3/n).
- Clustered data (several drafts per prompt): cluster bootstrap by prompt, 10,000 resamples.
- AUROC per detector (bootstrap CI); agreement: Fleiss' kappa on labels, Spearman on scores.
- Q3: McNemar's exact test on label flips; paired bootstrap on score change.
- Quality: per-criterion means with cluster-bootstrap CIs; follow-up experiments compare the same dev
  prompts with paired differences.
- Expected precision: 200 Tier A essays give about ±3 points on a 5% false-positive rate (±1.5 near
  1%); subgroups of 25-60 give wide intervals and are exploratory.

Decided now:
- Worth investigating: any detector whose false-positive interval lies wholly above 1% on Tier A, or
  any subgroup whose point estimate is at least double the overall rate; a significant McNemar result
  (p < 0.05) in Q3, investigated by looking at the editor's changes, never by tuning against detectors.
- Inconclusive: a detector missing more than 20% of results in a group, an interval wider than 15
  points, or raters with alpha below 0.4 on a criterion (that criterion is reported, not interpreted).
- Exclusions: generation errors and cap hits are kept and counted, not regenerated; human essays under
  150 words or with malformed text are excluded with reasons; detector errors are recorded as missing.

## 9. Failure modes and follow-up
From the dev set only: each recurring weakness with sample ids, frequency, effect, likely source
(prompt, model size, settings, post-processing) and alternatives. Candidate single-factor experiments,
judged on quality alone: (1) ask the writer for personal details before drafting personal pieces;
(2) a length check that retries once when a draft is under 70% of the target; (3) a two-step
outline-then-draft prompt; (4) a larger general model where it fits. Each gets its own plan.

## 10. Generator training data
None: the generator is the stock model. Gemma's pretraining data isn't disclosed, so contamination
with public corpora (PERSUADE, MICUSP) can't be ruled out and is listed as a limitation. Model terms are
to be checked. The editor's data was audited separately (AUDIT.md) and doesn't generate essays.

## 11. Compute
About 40 s per 500-word draft on this laptop (existing runs): dev ~180 drafts ≈ 2 h, eval 146 drafts ≈
1.6 h; pipeline B adds ~3 s per paragraph (≈ 15 min). Local detectors: unknown until chosen (likely
1-3 h on 8 GB, if they fit). Model judges: two per packet.

## 12. Before anything runs
- Ollama has downloaded 0.40.10 and installs on restart; pin the version for the whole experiment.
- Confirm data licenses for the human controls; get the original detector details from you.
