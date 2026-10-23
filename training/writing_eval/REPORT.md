# Writing quality investigation: drafter and editor

Run on 2026-10-22. All numbers below come from saved runs in `training/writing_eval/runs/` (git-ignored) and
blind judgments in `training/writing_eval/judgments/`. Exact prompts and settings for every configuration are
in `training/writing_eval/configs/` and `training/prompt_candidates.py`.

## What was tested

| | |
|---|---|
| Drafter | `gemma4:e4b` (Ollama), thinking on (default) |
| Editor | `quill-editor-v7` (Qwen3-4B-Instruct-2507, QLoRA round 7), temperature 0 |
| Drafting inputs | 16 assignments (`assignments.jsonl`) × 2 voice conditions (assigned preset, none) = 32 drafts per configuration, seeds 1000-1031 for every configuration |
| Editing inputs | 40 eval paragraphs (`eval_set.jsonl`), 150 reliability paragraphs (`data-confirm`), 54 human-written passages (`data/human_corpus`, below) |
| Human comparison | 54 passages written before late 2022: 17 MICUSP student papers, 9 WAC Clearinghouse book passages (via LibreTexts), 15 SEC 10-K MD&A sections (FY2019-21), 13 Kubernetes concept docs (Dec 2021). Licenses in `data/human_corpus/manifest.jsonl`. Used for evaluation only. |
| Judges | Claude subagents reading blinded packets (labels shuffled with fixed seeds, key held separately). They are model judges, not people: treat them as one more instrument, not ground truth. |

Configurations (one major change at a time):

| Drafting | System prompt | Settings |
|---|---|---|
| original | live `DRAFT_SYSTEM`, "N paragraphs" length | temperature 0.75, top_p 0.9, repeat_penalty 1.1 |
| prompt-only | `DRAFT_SYSTEM_V2`, length in words only | same as original |
| improved | `DRAFT_SYSTEM_V2` | temperature 0.8, min_p 0.05, top_p 1.0, repeat_penalty 1.0 |
| scaffold | `DRAFT_SYSTEM_V3` (V2 + personal-material rule) | same as improved |

| Editing | System prompt |
|---|---|
| original | live `editor.SYSTEM` (the one v7 was trained with) |
| v2-proofread / v2-clarity | `EDIT_SYSTEM_V2` with an explicit mode line |

**AI detectors were not run.** Drafts from the drafter are AI-written, so a detector flagging them is a correct
result, and tuning the drafter to lower those scores would be evasion; there is also no detector access here.
The question that does matter for real writers, whether the editor makes human writing read differently, is
measured directly below (voice shift, unnecessary and harmful edits, meaning kept).

## Results

### Drafter

Blind ratings, 1-5 (32 items, 4 judges, one item each). Paired difference vs original with 95% bootstrap interval:

| | original | prompt-only | improved |
|---|---|---|---|
| adherence | 4.06 | 3.97 (-0.09 [-0.59, +0.38]) | 3.91 (-0.16 [-0.59, +0.25]) |
| honesty | 3.47 | 3.34 (-0.12 [-0.62, +0.38]) | 3.62 (+0.16 [-0.25, +0.56]) |
| development | 3.25 | 3.34 | 3.44 (+0.19 [-0.28, +0.66]) |
| coherence | 3.69 | 3.75 | 3.88 (+0.19 [-0.22, +0.59]) |
| voice fit | 3.69 | 3.81 | 3.94 (+0.25 [-0.03, +0.59]) |
| shaped to its purpose | 3.00 | 3.31 (+0.31 [-0.12, +0.78]) | **3.41 (+0.41 [+0.03, +0.78])** |
| ranked first | 31% | 28% | 41% |

Only "shaped to its purpose" clears zero, for `improved`. Everything else is within noise at n = 32.

Descriptive measures (medians per text; human columns for reference, not targets; genres differ):

| | original | prompt-only | improved | MICUSP | WAC | SEC | K8s |
|---|---|---|---|---|---|---|---|
| conclusion starts "Ultimately / In conclusion..." | 19/31 | 5/31 | 9/32 | 0/17 | 0/9 | 0/15 | 0/13 |
| formulaic sentence openers per 100 sentences (median) | 4.5 | 0.0 | 0.0 | 4.2 | 4.0 | 0.0 | 0.0 |
| stock words per 1000 (mean) | 4.5 | 2.1 | 2.7 | 0.0* | 1.4* | 0.0* | 0.0* |
| lexical diversity (MTLD) | 185 | 184 | **95** | 81 | 82 | 67 | 57 |
| sentence-length spread (CV) | 0.33 | 0.35 | 0.37 | 0.49 | 0.45 | 0.58 | 0.45 |
| paragraph-length spread (CV, mean) | 0.10 | 0.15 | 0.14 | 0.25 | 0.23 | 0.35 | 0.25 |
| words (mean; target ~500) | 464 | 394 | 419 | | | | |
| failed or empty drafts | 1 | 1 | 0 | | | | |

\* medians. Cross-assignment 4-gram overlap was near zero for every configuration (0.04-0.06% of n-grams), so
the sameness is structural (template, openers, conclusions, even paragraph sizes), not repeated wording.

Personal pieces (10 items: narrative, scholarship, camp job, blog, letter to parents), blind honesty count:

| | improved | scaffold |
|---|---|---|
| invented personal specifics per draft (median, range) | 3.0 (0-7) | 5.5 (0-8) |
| drafts with nothing invented | 1/10 | 2/10 |
| honesty (1-5) | 2.5 | 2.7 |

In the first round, honesty on personal pieces was 2.8 (original), 2.2 (prompt-only), 2.6 (improved), against
3.8-4.1 on the other 22 assignments.

### Editor

| | original | v2-proofread | v2-clarity |
|---|---|---|---|
| reliability: planted mistakes fixed (150 paragraphs) | **93%** | 92% | 90% |
| reliability: paragraphs exactly right / clean ones untouched | 95% / 98% | 95% / 98% | 95% / 98% |
| eval: writing problems caught (40 paragraphs) | **24/29** | 22/29 | 19/29 |
| eval: voice choices kept | 14/14 | 14/14 | 14/14 |
| blind, 40 paragraphs: errors fixed / voice kept (1-5) | 4.70 / 4.90 | 4.67 / 4.88 | 4.67 / 4.88 |
| blind, 40 paragraphs: meaning kept | 40/40 | 40/40 | 40/40 |

On the 54 human passages (blind verdict on each change, 29 passages that either editor changed):

| | changes | fix | clarifies | unnecessary | harmful | meaning lost | voice lost | real errors missed |
|---|---|---|---|---|---|---|---|---|
| original | 52 | 31 | 3 | 8 | **10** | 10 | 11 | 37 |
| v2-clarity | 67 | 35 | 5 | 16 | **11** | 8 | 15 | 31 |

By source, harmful changes from the live editor: MICUSP 5/38, Kubernetes 3/8, SEC 2/4, WAC 0/2. Examples:
inserting the wrong subject into a technical sentence, a dangling "however", "attestations" → "demands",
adding "Inc." to an organization's name. The edits are almost all small (71% small fixes, 12% punctuation,
0% rewrites) and produce no measurable style shift on human text (contractions, word length and sentence
length all change by under 0.1%).

### Which stage introduces the patterns

| | edited essays | edits per 1000 words | style shift |
|---|---|---|---|
| live editor on live drafts (31) | 1 | 0.07 | none measurable |
| new editor on live drafts | 2 | 0.14 | none |
| live / new editor on improved drafts (32) | 0 | 0 | none |
| live editor on human text (54) | 25 | 1.8 | none |
| new editor on human text | 27 | 2.3 | none |

The editor barely touches generated drafts and does not move any of the drafter's patterns. **The template,
the reflexive openers and conclusions, the even paragraph and sentence lengths, and the inflated lexical
variety all come from the drafter.**

### Training data (`audit_training_data.py`, `audit_coedit.py`)

- 10,033 examples; 81% carry the generic "no samples" voice line (CoEdIT, plus 7 app-feedback rows).
- Kinds of change in the targets: CoEdIT simplification (4,668 edits) is 76% full rewrites, 51% add content
  words the source didn't have, 70% drop 40%+ of the source's content words. CoEdIT clarity (508) adds content
  in 24% (one target turns "Microsoft decided to press charges against a teacher" into "Russian prosecutors
  have charged a school headmaster"). GEC (8,168) is mostly small fixes and swaps; 0.5% of its targets are
  corrupted, keeping the wrong word beside the fix ("give me advise advice").
- 12.6% of CoEdIT edits remove a contraction (often while rewriting: "It'll be used..." → "It will only be
  used..."); 5% of the casual examples do, and those are real its/it's fixes.
- 627 exact duplicate (source, target) pairs; 50 source sentences trained toward two different targets;
  1,927 paragraphs share an opening with another (the 3 planted-error variants per casual paragraph).
- Reasons: one sentence ("Makes the sentence simpler and easier to read") is the target 3,582 times.
- The casual training paragraphs were written by gemma, not people, so the model's idea of casual voice is
  gemma's.

Measured effect on behavior: limited. The editor makes no rewrites on human text and no measurable formality
shift, so the rewrite- and formality-heavy targets are not showing up as rewriting. What does show up is
mis-fixing prose it doesn't understand (technical and corporate text), and missing real errors.

## Most likely explanations, with confidence

1. **High.** The drafter's sameness is structural and comes from the drafter itself: the old length setting
   names a paragraph count, and with no voice chosen the prompt asks it to "keep the writer's existing tone"
   of text that doesn't exist, so it falls back on one house template (61% formula conclusions, even
   paragraph sizes). The revised prompt cut formula conclusions to 16-28% and stock words by about 40%.
2. **High.** `repeat_penalty 1.1` inflates word variety to roughly 2-3× human levels (MTLD 184 vs 57-82),
   consistent with synonym-swapping. Removing it was the only decoding change between prompt-only and
   improved, and MTLD fell from 184 to 95 while ratings didn't drop.
3. **High.** The drafter invents personal experiences for personal pieces whatever the prompt says, including
   a prompt written only to stop it. This is a model-capability limit at this size, not a wording problem.
4. **Medium.** The editor is not a source of homogenization, but about one in five of its changes on real,
   out-of-domain prose makes things worse, and the candidate prompt doesn't help. The fine-tuned model follows
   its training prompt; new instructions at inference lowered accuracy (93% → 90%, 24 → 19 of 29).
5. **Low to medium.** The CoEdIT problems (paraphrase targets, content changes, corrupted and duplicate
   examples) are real data-quality issues, but there is no evidence here that they cause formalizing behavior.
   They may contribute to the harmful edits and missed errors; only a retraining ablation can show that.

## Changes, and what the evidence supports

**Drafting: adopt `improved`** (`DRAFT_SYSTEM_V2`, `draft_prompt_v2`, `DRAFT_OPTIONS_V2`). Measured: better
shaped (+0.41, interval above zero), fewer formula conclusions and stock words, word variety near human
levels, no failures. Trade-offs: drafts run short (419 vs ~500 words) and adherence is a little lower
(-0.16, not significant). Also fixed in the app: one reply item holding several paragraphs no longer gets
merged into one (`editor.draft_stream`).

**Personal pieces need a product change, not a prompt.** Ask the writer three to five specific questions
(what happened, who was there, what was said) before drafting, draft only from their answers, and run the
invented-specifics check on the result, showing anything flagged to the writer. Not built yet.

**Editing: keep the live prompt for v7.** Use `EDIT_SYSTEM_V2` (explicit proofread / clarity / structure /
substance modes) only as the prompt in the next training round's data, so the model learns it rather than
reading it cold.

**Inference safety:** cap generation (`num_predict` around 600 for edits, 1,500 for drafts). Two runs in this
investigation stalled for minutes with nothing to stop them, and a review in the app would wait up to 5 minutes.

**Training data (if there is a round 8):** drop CoEdIT simplification and clarity targets flagged
`adds_content` or `drops_content`, the 42 corrupted GEC targets, duplicates, and conflicting pairs; replace the
templated reasons; add no-edit and light-fix examples from professional and technical prose (from sources
other than `data/human_corpus`, which stays held out); and use real human casual writing instead of
gemma-written paragraphs where licensing allows. Judge round 8 on reliability, eval, and the human-text
verdicts above, and adopt it only if harmful edits on human text fall without losing accuracy.

## Limitations

- Judges are language models, not people. A human blind rating on the same packets
  (`training/writing_eval/packets/`) would be the stronger test.
- Small samples: 32 drafts, 40 + 150 paragraphs, 54 human passages; only "shaped" separates from noise.
- One seed per item; drafts at temperature 0.75-0.8 vary between runs.
- Human genres (student papers, books, annual reports, docs) differ from the assignments, so the descriptive
  comparison shows ranges, not targets. Lexical-diversity and length-spread figures are descriptive only.
- The invented-specifics heuristic undercounts; judges counted more.
- An Ollama outage (15:45-16:05) invalidated the first batch's editor results; all editor numbers here are
  from the re-run, and the scripts now retry and stop instead of scoring server errors as "no edits".

## Reproducing

```
.venv\Scripts\python training\audit_training_data.py
.venv\Scripts\python training\audit_coedit.py --examples 3
.venv\Scripts\python training\human_corpus.py all
powershell -File training\writing_eval\run_all.ps1        # drafts, editor runs, accuracy tests
powershell -File training\writing_eval\run_editor.ps1     # editor re-runs, pipelines, human text
.venv\Scripts\python training\compare_writing.py report original prompt-only improved
.venv\Scripts\python training\compare_writing.py stages
.venv\Scripts\python training\judge_packets.py make all   # then judge the packets blind
.venv\Scripts\python training\judge_packets.py score
```
