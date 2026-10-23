# Fine-tuning pipeline audit

Repository state as of commit `2e07a1b` (2026-10-22). Facts come from the code and from
`training/audit_pipeline.py`, `audit_training_data.py`, `audit_coedit.py` and the experiment in
[REPORT.md](REPORT.md); anything not measured is marked as such.

## 0. What's actually fine-tuned

Only the **editor** is fine-tuned. The **generator** (drafting) is `gemma4:e4b` served as-is by
Ollama; it has no training data or training run in this repository, so the dataset and training
audits below apply to the editor only. The generator's behavior is shaped by its prompt and
decoding settings (`editor.DRAFT_SYSTEM`, `config.DRAFT_OPTIONS`).

## 1. Training audit (editor, `training/train.py`)

| | |
|---|---|
| Base model | `unsloth/Qwen3-4B-Instruct-2507` (Apache-2.0), loaded in 4-bit |
| Method | QLoRA via Unsloth: r 16, alpha 16, dropout 0, all attention and MLP projections |
| Optimizer / schedule | AdamW 8-bit, learning rate 2e-4, cosine, 3% warmup, bf16 |
| Batch | 2 per device × 8 accumulation = 16 examples per step |
| Epochs | 1 (round 7: 628 steps over 10,033 examples) |
| Sequence length | 2,048; estimated longest example about 1,170 tokens, so nothing is truncated |
| Loss masking | `train_on_responses_only`: loss only on the assistant's JSON answer, not the system prompt or paragraph |
| Chat template | Qwen's, with the empty `<think>` block removed so training matches Ollama's serving template |
| Validation during training | first 100 of the 528 validation examples, every 120 steps |
| Checkpoint selection | none: the last step is exported (`best_model_checkpoint` is None in every run) |
| Export | merged LoRA → GGUF Q4_K_M → Ollama, with `PARAMETER temperature 0.3` (overridden by the app to 0) |
| Seeds | dataset shuffle `random.seed(7)`; trainer default seed (42, not set explicitly) |

Loss curves (from each run's `trainer_state.json`; round 4's checkpoints were not kept):

| Run | Train loss, first → last logged | Eval loss by step |
|---|---|---|
| round 5 (`out-run5`) | 1.628 → 0.135 | 0.189, 0.162, 0.156, 0.155 (451) |
| round 6 (`out-run6`) | 1.630 → 0.136 | 0.160, 0.138, 0.127, 0.126 (479) |
| round 7 (`out`, live) | 1.727 → 0.142 | 0.183, 0.157, 0.145, 0.141, 0.139, 0.139 (628) |

Findings:
- **Eval loss is flat at the end of every run** (round 7: 0.1392 at steps 600 and 628), so a second epoch
  or a best-checkpoint rule would change little. There's no sign of overfitting within one epoch, but
  see the leakage below before reading anything into the low values.
- **Eval losses can't rank the rounds.** Each round built its own validation set from its own data
  mix, so round 6's lower eval loss (0.126) and round 7's (0.139) measure different sets. The rounds
  were compared on fixed external tests instead (reliability, eval), which is the right call.
- The served model is the 4-bit quantized export, not the trained adapter. All external tests ran
  against the served model, so the numbers describe what users get.

## 2. Dataset audit (editor, `training/data/`)

| | train | val |
|---|---|---|
| Examples | 10,033 | 528 |
| CoEdIT-derived (generic "no samples" voice line) | 8,107 (81%) | 414 |
| Casual paragraphs with planted errors | 1,926 (19%) | 114 |

**Sources and licensing**

| Source | License or terms | Notes |
|---|---|---|
| `grammarly/coedit` | Apache-2.0 per its dataset card | The card says the data was curated from public datasets and doesn't list them; it also notes some tasks were withheld for licensing reasons. The underlying sources' own licenses were not verified here. |
| Casual paragraphs (`data-casual`, 680) | Written by `gemma4:e4b` locally (Gemma terms) | Not human writing: the model learns gemma's idea of a casual voice. |
| App feedback (accepted suggestions, 7 rows ×3 weight) | Family members' own writing | Disclosed in the app ("Suggestions you accept help train Quill"). |

**Genre**: CoEdIT is mostly encyclopedic, news, academic-abstract and learner-English sentences; the
casual set is first-person personal-essay and blog paragraphs on 36 everyday topics. There is no
professional, technical or business prose, which matches where the editor makes harmful edits
(Kubernetes 3 of 8 changes, SEC 2 of 4).

**Duplicates**: 956 exact duplicate paragraphs and 221 exact duplicate whole examples in train; 627
duplicate (source, target) edit pairs; 50 source sentences trained toward two different targets.

**Example quality** (`audit_coedit.py`): CoEdIT simplification targets (4,668 edits) are 76% full
rewrites, 51% add content words the source didn't have, and 70% drop at least 40% of the source's
content words. Clarity targets add content in 24% (including changed facts). 42 grammar targets are
corrupted, keeping both the wrong word and its fix. 12.6% of CoEdIT edits remove a contraction.

**Input-output consistency**: every edit's quote is present in its paragraph (0 missing); 1 edit
doesn't change anything. Two systematic inconsistencies:
- The "Essay goal" line on casual examples is drawn at random from six goals, independent of the
  paragraph, and every CoEdIT example says "not specified". The model is never shown a goal that
  matters, so it learns to ignore the goal line. That fits the app sending goal, audience and tone
  with little visible effect.
- Reasons are templated: one sentence is the target 3,582 times.

**Leakage**
- **Train ↔ val: yes, for the casual data.** All 114 casual validation examples share at least half
  their word 5-grams with a training example, because each casual paragraph appears three times with
  different planted errors and the split is random. CoEdIT validation is nearly clean (6 of 414).
  Validation loss is therefore optimistic for the casual part.
- **Train ↔ test sets: none found.** `eval_set.jsonl` (0/40), `data-heldout` (0/150), `data-confirm`
  (0/150), the drafting assignments (0/16) and the human corpus (0/54) share no paragraph with training
  at a 30% 5-gram threshold, and confirm doesn't overlap heldout.
- **Test sets used for decisions:** heldout tuned the grammar rules, confirm chose round 7, the
  temperature, and the editor prompt. Both are now development sets. **There is no untouched final
  test set**, and one is needed before any further claim (section 6).

## 3. Evaluation suite (reproducible; commands in REPORT.md)

| Test | What it isolates | Script |
|---|---|---|
| Generator alone | 4 drafting configurations × 32 drafts, fixed seeds | `compare_writing.py draft` |
| Editor on single paragraphs | accuracy (planted mistakes, hand-built cases) | `reliability.py`, `eval.py`, `compare_writing.py revise` |
| Editor on human-written drafts | 54 pre-2022 passages, 4 genres | `compare_writing.py human` |
| Editor on generated drafts | live and candidate drafts | `compare_writing.py pipeline` |
| Full pipeline | drafter → editor, all four live/candidate combinations | `compare_writing.py pipeline`, `stages` |
| Blind quality judging | adherence, honesty, development, coherence, voice, structure; meaning kept, unnecessary and harmful edits | `judge_packets.py make / score` |

Each run saves its exact prompts, settings and model (`writing_eval/configs/`); the batch scripts
(`run_all.ps1`, `run_editor.ps1`) retry server errors and stop rather than score them.

## 4. Quality results (summary of REPORT.md)

- Generator: the revised prompt and settings improved "shaped to its purpose" (+0.41, 95% interval
  +0.03 to +0.78, 32 items); other criteria moved within noise. Formula conclusions fell from 61% to
  28%. All configurations invent personal details in personal pieces (median 3-5.5 per draft).
- Editor: 93% of planted mistakes fixed, meaning kept on all 40 test paragraphs, near-zero unnecessary
  edits there; on human prose, 10 of 52 changes judged harmful and 37 real errors missed.
- Pipeline: the editor changes 0-2 of 31-32 generated drafts, so the generator's patterns pass through.

**Human review: not done.** All blind judging so far is by model judges (Claude subagents). The blinded
packets in `writing_eval/packets/` (local only) are ready for people; `judge_packets.py score` accepts
their judgments in the same JSON shape. Two or three raters on the 32 draft items and the 29 human-edit
items would be enough to check whether the model judges agree with people.

## 5. Detectors

**Not run.** Three reasons, stated plainly:
1. The generator's drafts are AI-written. A detector flagging them at 98-100% is a correct
   classification, not a false positive, and tuning the generator to lower it would be evasion; I won't
   build that loop. Quill marks AI-drafted text in the editor and in the writing history instead.
2. No detector is accessible here (no API keys), and testing would send essays to third parties.
3. The only legitimate question here, whether **human** writing passed through the editor gets
   misclassified, is better answered without a detector. The editor changes about 2 words per 1,000 on
   human text with no measurable style shift (section 4), which is direct evidence on that question.

On interpretation, for anyone reading detector numbers: a detector's "98% AI" is a model output score,
not a probability of authorship. Converting it into one needs calibration on a labeled set from the
same population (same genre, length, writer level), plus the base rate of AI use in that population. A
score that is well calibrated on one population can be badly miscalibrated on another; published
evaluations have found elevated false-positive rates on non-native English writing, and short texts are
less reliable. A valid false-positive study needs verified human controls (like `data/human_corpus`),
reported sample sizes, fixed detector versions and settings, per-genre rates, and agreement between
detectors, with scores treated as secondary to direct quality measures.

## 6. Recommendations (each tied to a measured result)

| Change | Evidence | Status |
|---|---|---|
| Drafting prompt and settings ("improved") | +0.41 shaped; formula conclusions 61% → 28%; word variety near human | **Done** (commit `2e07a1b`) |
| Output caps per job | stalls of minutes in two runs; caps at ~2× measured maximum | **Done** |
| Keep the live editor prompt | candidate prompt: 93% → 90-92% fixed, 24 → 19-22 of 29 | **Done** (no change) |
| Ask-the-writer-first for personal pieces | every prompt variant invents personal details | Not built |
| Round 8 data: drop flagged CoEdIT rewrites and content changes, corrupted and duplicate pairs; real goals or none instead of random; add light-fix and no-edit examples from professional and technical prose; split train/val by source paragraph | data audit above; harmful edits concentrated in technical and corporate text | Proposed. Change the data only, keep every hyperparameter, so the comparison isolates it. |
| A sealed final test set | heldout and confirm have been used for decisions | Proposed: e.g. new MICUSP papers (other students' IDs) and a third planted-error set on new topics, built once and scored only for the final decision |

## 7. Root causes, with confidence

| Hypothesis | Confidence | Evidence |
|---|---|---|
| The template writing comes from the generator's old prompt and decoding, not from training | High | Pipeline ablation: editor changes 0-2 of 31-32 drafts; prompt and decoding changes moved the patterns |
| `repeat_penalty 1.1` inflated word variety | High | Single-variable change: MTLD 184 → 95 (human 57-82) |
| The generator invents personal details because of model limits at this size, not wording | High | Four prompt variants, including one written only for this, all invent |
| The editor's harmful edits on professional prose come from missing genres in its training data | Medium | No technical or business prose in training; harmful rates highest there; small samples (8 and 4 changes) |
| CoEdIT rewrite targets make the editor rewrite or formalize | Low | Data shows the pattern; behavior doesn't (0% rewrites, no style shift) |
| The editor ignores goal, audience and tone because training gave it random or empty goals | Medium | Data audit; not yet tested behaviorally |

## 8. Remaining uncertainties

- Model judges, not people; small samples (32 drafts, 29 human-edit items); one seed per draft.
- Round 7's validation loss is optimistic for the casual data (leakage) and not comparable to earlier rounds.
- CoEdIT's underlying source licenses weren't traced.
- No detector data, by design (section 5).
