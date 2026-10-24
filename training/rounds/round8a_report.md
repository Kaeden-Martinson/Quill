# Round 8a report: professional no-edit ablation

2026-10-23. Plan: round8a_plan.md (approved before training). Sealed test not opened. No human ratings
yet; every blind result below is from two Claude model judges, not people.

## Decision
- **Not adopted.** Round 8a fails two of the round 8 criteria against round 7: reliability "fixed" is
  3 points lower on both test sets (limit 2), and unnecessary changes on human passages are 4 higher
  (limit 2). Round 7 stays live; nothing was deployed.
- **Mechanism: inconclusive.** Round 8a's blind errors fixed (4.6375) is 0.075 below round 7 and
  exactly 0.100 above round 8. The plan's "supported" condition (within 0.1 of round 7, harmful below
  round 7) and its "not supported" condition (within 0.1 of round 8) both hold, and the plan didn't say
  what happens when both do. I didn't pick one; the data sit midway.

## What was run
- Intervention: 968 professional no-edit training examples removed (round8a_removed.jsonl); validation
  unchanged. 8,181 examples, 512 steps; train.py unchanged (sha256 72de6038…, same as round 8).
- Model `quill-editor-v8a` (weights sha256-70deb909…; Modelfile otherwise identical to v8). v7 and v8
  untouched. Snapshot: out-run8a, data-run8a, round8a.json.
- Development suite with the same scripts, settings (temperature 0, 800-token cap) and Ollama 0.40.4 as
  round 8's v7 and v8 runs, whose results are reused.
- Blind judging: new three-way packets (r8a), labels counterbalanced (each model in each position 10-14
  times), two Claude judges per packet with round 8's instructions adapted for three editors. Agreement:
  revisions 40/40 (kappa 1.0); human-passage verdicts 119/125 (kappa 0.919).

## Results

| Measure | v7 | v8 | v8a |
|---|---|---|---|
| Reliability heldout: fixed / perfect / untouched / extra | 96 / 94 / 98 / 0.03 | 98 / 96 / 100 / 0.03 | 93 / 93 / 100 / 0.03 |
| Reliability confirm: fixed / perfect / untouched / extra | 93 / 95 / 98 / 0.02 | 92 / 96 / 98 / 0.01 | 90 / 95 / 98 / 0.01 |
| Eval: writing / voice / invented | 24/29, 14/14, 0 | 23/29, 14/14, 0 | 24/29, 14/14, 0 |
| Human passages: edits made (passages touched) | 49 (26) | 30 (16) | 46 (26) |
| Blind, human passages (summed over 2 judges): harmful | 18 | 8 | 15 |
| meaning lost | 18 | 8 | 11 |
| unnecessary | 11 | 1 | 15 |
| missed errors | 70 | 93 | 82 |
| Harmful / unnecessary on SEC | 6 / 0 | 0 / 0 | 2 / 6 |
| Harmful / unnecessary on Kubernetes | 4 / 5 | 2 / 0 | 5 / 4 |
| Harmful / unnecessary on MICUSP (student) | 8 / 6 | 4 / 1 | 6 / 3 |
| Harmful / unnecessary on WAC (academic) | 0 / 0 | 2 / 0 | 2 / 2 |
| Blind revisions: errors fixed (of 5) | 4.7125 | 4.5375 | 4.6375 |
| Blind revisions: meaning kept | 40/40 | 40/40 | 40/40 |

Both judges point the same way on human passages (harmful, meaning lost, unnecessary): judge 1 gives
v7 9/9/5, v8 4/4/0, v8a 7/5/7; judge 2 gives 9/9/6, 4/4/1, 8/6/8.

Round 7 and 8 were re-judged in this three-way comparison; their numbers are close to the earlier
two-way judging (errors fixed 4.71 / 4.50 then, 4.71 / 4.54 now; harmful 18 / 8 both times).

## Criteria (round 8's, verbatim, v8a against v7)

| Criterion | v8a vs v7 | Result |
|---|---|---|
| Heldout: fixed and perfect each ≤ 2 below; untouched ≥ 95% | fixed −3, perfect −1, untouched 100 | **fail** |
| Confirm: same | fixed −3, perfect 0, untouched 98 | **fail** |
| Eval: writing ≤ 1 below; voice not lower; nothing invented | 0, 0, 0 | pass |
| Human: fewer harmful | 15 vs 18 | pass |
| Human: meaning lost not higher | 11 vs 18 | pass |
| Human: unnecessary ≤ 2 higher | 15 vs 11 (+4) | **fail** |
| Revisions: meaning kept on all 40 | 40/40 | pass |
| Revisions: errors fixed ≤ 0.1 lower | −0.075 | pass |
| NEW: harmful on SEC + Kubernetes ≤ v7 | 7 vs 10 | pass |

## What the ablation shows, and doesn't
- Removing the professional no-edit examples brought back most of round 7's willingness to edit: v8a
  touches as many human passages as v7 (26), and its SEC + Kubernetes edits go from 2 (v8) back to 13.
  On SEC prose the extra edits are now mostly judged unnecessary (6) rather than harmful (2, v7 had 6).
- It did not bring back round 7's accuracy on planted mistakes: reliability "fixed" is lower than both
  v7 and v8 on both sets. Round 8 had not lost that ability, so this is not "round 8's abstention
  removed"; it is a different trade-off.
- Paragraph revisions: the difference between models comes from 5 of 40 items. v8a matches v7 on one
  (app-01), beats both on one (opin-02) and matches v8's misses on three (hist-03, blog-02, voice-04).
  That is too few items to locate the cause.
- Confounds carried with the intervention (stated in the plan): 10.6% fewer examples, 60 fewer steps, a
  lower no-edit share overall. One run, one seed. This can't attribute round 8's behaviour to the
  professional examples alone, and the plan's mechanism rule doesn't settle it.

## Sealed test
Unopened. Round 8's protocol scores it once for round 7 and the selected model; the selected model is
still round 7. Nothing here changes that.

## Not done
- Human ratings: the r8h sheets (round 7 vs 8) are ready; none collected. No r8a sheets were made for
  people (the plan made them optional).
