# Round 8 report

Written 2026-10-23 after the development evaluation, before the sealed test was opened.
Plan and rules: [round8_plan.md](round8_plan.md), written before the data was rebuilt or any training.
Labels: **Observed** = measured; **Interpretation** = my reading; **Hypothesis** = untested.

## 1. Current state

| | |
|---|---|
| Round 7 frozen | done: `training/out-run7`, `training/data-run7`, `round7.json` |
| Round 8 data, training, model build | done: `training/out-run8`, `training/data-run8`, `round8.json`, `quill-editor-v8` |
| Integrity audit | done, 0 problems: `round8_integrity.json` (`verify_round8.py`) |
| Development suite, both models | done: logs `training/writing_eval/logs/r8-*.log`, outputs `training/writing_eval/runs/*@v7.jsonl`, `*@v8.jsonl`, `training/eval_results/*quill-editor-v{7,8}*` (earlier results archived in `eval_results/_before_round8_eval`) |
| Model-judge blind ratings | done: `training/writing_eval/judgments/r8-*-claude{1,2}.json` |
| **Human blind ratings** | **not collected.** Sheets ready: `training/writing_eval/packets/people/r8-*.md/.csv`; instructions `training/writing_eval/HUMAN_REVIEW.md` |
| Decision under the written rules | made (section 7): **not adopted** |
| Sealed test | **unopened, unscored** (hash matches; no `sealed_log.jsonl`) |

## 2. Integrity audit (Observed)

- Hashes: all 10 round 7 files, `train.py`, Ollama's `quill-editor-v7` build, round 8 `train.jsonl` and `val.jsonl`, and the sealed cases match their records.
- Exclusions: 6,886 logged + 18,614 kept = the 25,500-row pool; reasons match the manifest; every row has a CoEdIT `_id`; none excluded twice; 6,204 CoEdIT paragraphs × 3 = 18,612 rows (2 left over at split ends).
- Professional counts are different units: 1,068 source paragraphs (45 documents) → 1,068 no-edit + 337 light-edit = 1,405 examples → 1,270 train + 135 val (split by document).
- Examples: 9,149 train and 533 val all parse; every quote is in its paragraph; every system prompt is the app's; 2 training edits change nothing.
- Leakage: 0/533 validation examples near-duplicate training (round 7: 114/114 casual); 0 overlap between training and eval (40), heldout (150), confirm (150), sealed (150), human corpus (54).
- Duplicates: 1,025 exact duplicate training examples. Same mechanism as round 7 (955 copies that differed only in the random goal line): a casual paragraph's three variants collide. Not repaired; comparable in both rounds.
- Sealed set: when built, scripts hashed it and checked it for overlap (0/150); no model has been run on it.

## 3. Training results (Observed)

| | Round 7 | Round 8 |
|---|---|---|
| Base / method / settings | Qwen3-4B-Instruct-2507, QLoRA r16, lr 2e-4 cosine, 1 epoch, batch 16 | identical (`train.py` hash unchanged) |
| Examples / steps | 10,033 / 628 | 9,149 / 572 |
| Duration | (not recorded) | 9,195 s |
| Mean training loss | 0.142 (last logs) | 0.1405 |
| Validation loss by check | 0.183 → 0.139 | 0.134 → 0.114 → 0.105 → 0.100 → 0.0999 |
| Exported | last step | last step (`checkpoint-572`) |
| Ollama build | `sha256-1abb88dc…` | `sha256-5e3ca1ae…`, same template and parameters |

Warnings: only Unsloth's "Not an error" note on batch-loss averaging (also in earlier rounds). The validation losses
are on different sets (round 7's leaked), so they don't rank the rounds.

## 4. Round 7 vs round 8 (Observed; same day, same prompt, temperature 0, num_predict 800)

| Test | n | Round 7 | Round 8 |
|---|---|---|---|
| Reliability heldout: fixed / perfect / untouched / extra | 150 (102 mistakes, 63 clean) | 96% / 94% / 98% / 0.03 | **98% / 96% / 100% / 0.03** |
| Reliability confirm: fixed / perfect / untouched / extra | 150 (101 mistakes, 61 clean) | 93% / 95% / 98% / 0.02 | 92% / 96% / 98% / 0.01 |
| Eval: writing problems caught / voice kept / invented | 40 | 24/29 / 14/14 / 0 | 23/29 / 14/14 / 0 |
| Editor on single paragraphs: changed / edits | 40 | 20 / 25 | 19 / 21 |
| Editor on human passages: edited / edits (per 1,000 words) | 54 | 26 / 49 (1.70) | 16 / 30 (1.04) |
| Editor on generated drafts | 32 | 0 changed | 0 changed |
| Style shift on human text (contractions, word length, sentence length) | 54 | ~0 | ~0 |
| Failed replies | | 1 paragraph (see note) | same paragraph |

Blind model-judge ratings (two Claude judges, summed; Cohen's kappa between them on human-text verdicts 0.763, 69/79 agree):

| Human passages (28 with changes) | changes | fix | clarifies | unnecessary | harmful | meaning lost | voice lost | real errors missed |
|---|---|---|---|---|---|---|---|---|
| Round 7 | 98 | 60 | 5 | 15 | **18** | 18 | 15 | 65 |
| Round 8 | 60 | 43 | 4 | 5 | **8** | 8 | 3 | 86 |

By genre (harmful / all changes, both judges): Kubernetes 4/16 → 2/2; SEC 6/10 → 0/2; MICUSP 8/66 → 4/48; WAC 0/6 → 2/8.

| Paragraph revisions (40; 35 identical between models) | meaning kept | errors fixed (1-5) | unnecessary | preferred where they differ |
|---|---|---|---|---|
| Round 7 | 40/40 | 4.71 | 0.00 | 5/5 items, both judges |
| Round 8 | 40/40 | 4.50 | 0.00 | 0/5 |

Note: one 392-word paragraph (MICUSP history paper) gets no reply from either model: both hit the 800-token output cap
added on 2026-10-22 (done_reason "length"). Same for both, so the comparison is unaffected, but in the live app a
paragraph of roughly 350+ words now silently gets no suggestions. Not changed during the experiment.

## 5. Human review

Not done. No human ratings exist; everything in section 4 marked "blind" is from model judges (Claude subagents), which
agree with each other well (kappa 0.76) but are one model family and not a substitute for people. Human disagreement with
the model judges can't be assessed yet.

## 6. Failure analysis (Observed examples; Interpretation in italics)

- Round 8 avoided harmful edits round 7 made: inserting the wrong subject into Kubernetes docs ("…changes to groups…"),
  "attestations" → "demands", a tacked-on "however", reversing "women's enslavement to men", and all 3 of round 7's
  harmful changes to SEC prose.
- Round 8 missed real errors round 7 fixed, on casual and student text: "There was crumbs everywhere", "Teenagers
  bodies", "Southern states own declarations", a comma splice ("…like a movie, I took like two hundred photos").
- Round 8's own harmful edits: truncating a sentence (MICUSP EDU), misspelling an author's name (MICUSP PHI), "focused
  work" → "focused on work" (WAC).
- *Interpretation: round 8 is more conservative. It edits less, and its edits are more often right, but it leaves more
  real errors. The trade-off is clearest in the two directions the rules care about: harmful edits on real prose (better)
  and errors fixed in casual paragraphs (worse).*

## 7. Decision rules (quoted from round8_plan.md: "Adopt round 8 only if all of these hold")

| Criterion | Round 7 | Round 8 | Result |
|---|---|---|---|
| Reliability heldout: fixed, perfect each ≥ round 7 − 2 pts; untouched ≥ 95% | 96, 94, 98 | 98, 96, 100 | pass |
| Reliability confirm: same | 93, 95, 98 | 92, 96, 98 | pass |
| Eval: writing ≥ round 7 − 1; voice not lower; nothing invented | 24, 14, 0 | 23, 14, 0 | pass (at the limit) |
| Human passages, blind: fewer harmful | 18 | 8 | pass |
| … meaning lost not higher | 18 | 8 | pass |
| … unnecessary no more than 2 higher | 15 | 5 | pass |
| Paragraph revisions, blind: meaning kept on all 40 | 40/40 | 40/40 | pass |
| … errors fixed no more than 0.1 lower | 4.71 | 4.50 (−0.21) | **fail** |

## 8. Recommendation

**Under the rules as written, round 8 is not adopted:** one of eight criteria fails. The failure is consistent rather than
noisy (all 5 differing paragraphs, both judges), so it isn't a borderline call.

Uncertainty: the "blind" criteria were applied with model judges only. The plan doesn't say who the judges must be, so the
rule can be applied as is; human ratings could still change the picture. Round 7 stays live.

## 9. Sealed test status

Unopened. The plan says it "is scored once, after the decision above, for both round 7 and the selected model". With round
8 not adopted, the selected model is round 7, so the sealed run would score round 7 only. Opening it now would use up the
sealed set before human ratings exist. Waiting on your call (see the end of the conversation).

## 10. Next steps

1. Human blind ratings on `packets/people/r8-*` (2-3 raters), then re-score; this is the evidence the decision most lacks.
2. Fix the output cap for long paragraphs in the live app (e.g. scale it with paragraph length) after the experiment closes.
3. Follow-up ablation, supported by the observed trade-off (more conservative, fewer harmful edits, more missed errors):
   - Hypothesis: the 1,068 professional no-edit examples taught abstention, causing both the fewer harmful edits and the
     missed errors; the CoEdIT exclusions did not.
   - One variable: round 8's data with the professional examples removed (everything else, including the split and
     goal labels, as in round 8).
   - Controls: train.py, settings, prompt, the same suite and judges; compared against round 8 and round 7.
   - Decision rule (fixed before running): if removing them restores errors fixed to within 0.1 of round 7 and the
     harmful-edit count stays below round 7's, the professional set is the cause and its no-edit share should be reduced
     (e.g. to match light-edit examples); otherwise the CoEdIT changes are implicated.
   - This does not claim either change caused anything yet; round 8 changed several data properties at once.
