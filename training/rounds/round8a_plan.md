# Round 8a plan: professional no-edit ablation (draft, awaiting approval; nothing trained)

Written 2026-10-23, after round 8's results were seen (round8_report.md). Because the round 8 results
are known, the thresholds below that are new (marked NEW) need approval before training.

## Hypothesis
Round 8's professional no-edit examples taught the editor to abstain: they produced both its fewer
harmful edits on real prose and its missed errors on casual and student writing. Removing them should
restore error correction on casual and student text, possibly at the cost of more harmful or
unnecessary edits on professional prose.

## The one intervention
Remove the 968 professional no-edit examples from round 8's training set (`training/data-run8/train.jsonl`).
- Traced in `training/rounds/round8a_removed.jsonl`: each removed example's line in round 8's file and
  its source paragraph id (605 Python docs, 363 SEC). These are exactly the training examples with no
  edits, a professional goal label, and a paragraph identical to a `data/pro_prose` source paragraph.
- The 1,068 figure quoted elsewhere counts training and validation together; 100 of them are in
  validation, which is left unchanged (byte-identical to round 8), so validation loss is comparable
  between round 8 and 8a.
- Kept: all 302 professional light-edit examples and every other example, label and relative order.
  Result: `training/data-r8a/train.jsonl` (8,181 examples, sha256 `436c7c69…`), `val.jsonl` unchanged.

Consequences of the intervention (not compensated):
- 968 fewer training examples (−10.6%); 512 steps instead of 572 at the same batch size and one epoch,
  so the cosine schedule runs over fewer steps.
- Share of no-edit examples 31.1% → 22.9%; professional share 13.9% → 3.7%.
These travel with the intervention: the ablation can't separate "no professional no-edit examples" from
"fewer no-edit examples overall" or "fewer steps".

## Fixed controls
`train.py` (sha256 recorded in round7.json), base model, LoRA and optimizer settings, epochs, sequence
length, loss masking, export procedure, Modelfile parameters; app inference settings (`EDIT_OPTIONS`,
including the 800-token cap, which stays as it was for every model in this comparison); the live editor
prompt; every evaluation script and set.

## Procedure
1. Copy `data-r8a/*` into `training/data/` (after checking `data/` still equals `data-run8`, which keeps
   round 8's copy), run `train.py` unchanged, snapshot to `training/out-run8a`, build `quill-editor-v8a`.
   `quill-editor-v7` and `-v8` are not touched.
2. Integrity: dataset hashes vs `round8a_dataset.json`; checkpoint and logs; Ollama build differs from
   v8 only in weights.
3. Run the development suite (`run_round8_eval.ps1` with v8a) for v8a; v7 and v8 results from
   2026-10-23 are reused only if the settings and scripts are unchanged since, otherwise all three rerun.
4. Model judges: new 3-way blind packets (v7, v8, v8a) for paragraph revisions and human passages,
   two judges each. Human raters: optional for this ablation; the r8h human review continues as planned.

## Measures (all saved per example)
1. Real errors fixed in casual and student writing: blind "errors fixed" on the 40 paragraphs; eval
   writing problems caught; reliability fixed.
2. Harmful edits and meaning lost on the 54 human passages (blind).
3. Unnecessary edits and untouched clean text: blind unnecessary; reliability untouched and extra.
4. Paragraph revisions: blind errors fixed, meaning kept.
5. Technical and business prose: harmful and unnecessary edits on the SEC and Kubernetes passages.
6. Unseen sources: the human corpus (no source in training) by genre.
7. Regressions: reliability heldout and confirm.

## Decision rules
A. Adoption (replace round 7): the eight round 8 criteria in round8_plan.md, verbatim, applied to round
   8a against round 7. Plus NEW: harmful edits on SEC + Kubernetes passages not more than round 7's
   (protects the professional prose round 8 improved most).
B. Mechanism (NEW, from round8_report.md section 10, stated before training):
   - Supported: round 8a's blind errors fixed is within 0.1 of round 7 and its harmful edits on human
     passages stay below round 7's.
   - Not supported: round 8a's blind errors fixed is within 0.1 of round 8's (the conservatism didn't
     move), which points at the other round 8 data changes.
   - Otherwise inconclusive.
   Either way it is one run with one seed and three confounded consequences (above); it can support or
   weaken the hypothesis, not prove a cause.

## Sealed test
Not used. Round 8's protocol (score once after its decision, for round 7 and the selected model) is
unchanged; this plan doesn't add models to it. Any change to that needs separate approval.
