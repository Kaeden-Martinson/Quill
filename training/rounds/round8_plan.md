# Round 8 plan (written 2026-10-22, before the dataset was rebuilt or any training)

## Question
Does changing only the training data make the line editor more reliable on real prose (fewer harmful
and unnecessary edits, meaning kept) without losing accuracy on the tests round 7 passed?

## What changes (the one variable: data)
1. CoEdIT exclusions, each logged with its CoEdIT `_id` and reason (`training/rounds/round8_exclusions.jsonl`):
   simplification and clarity targets that add or drop content; corrupted grammar targets (wrong word
   kept beside its fix); exact duplicate (source, target) pairs beyond the first; source sentences with
   conflicting targets (all copies); sources that still contain the task instruction.
2. Train/validation split by source before variants: CoEdIT by `_id`, casual paragraphs by paragraph,
   professional prose by document. Validation examples with a near-duplicate in training are dropped.
3. "Essay goal": a consistent "not specified" for casual and CoEdIT (their real purpose is unknown);
   grounded labels for professional prose from its source ("annual report (MD&A)", "technical documentation").
4. Professional prose (`data/pro_prose`, SEC 10-K MD&A FY2016-18 and Python docs v3.10.0): explicit
   no-edit targets (the human text as written) and light-edit targets (errors planted by `errors.py`, fix
   only those). Revision targets come from the CoEdIT clarity and coherence edits that pass the filters
   (human-written edits); no generated revision targets are added, since none of the new sources has
   human-made revisions and generating them would reintroduce a model's rewriting style.

Everything else stays as round 7: base model, `train.py` (hash recorded in `round7.json`), LoRA settings,
learning rate, schedule, batch, one epoch, sequence length, loss masking, export, and every inference
setting (`EDIT_OPTIONS`, the live editor prompt).

## Comparison
Round 7 (`quill-editor-v7`) and round 8 (`quill-editor-v8`), run the same day under the same settings on:
reliability `heldout` and `confirm`; `eval.py` (40); `compare_writing.py revise`, `human` (54 passages) and
`pipeline`; blind judging of paragraph revisions and of every change to the human passages.

## Selection (decided now)
Adopt round 8 only if all of these hold:
- reliability (heldout and confirm): mistakes fixed and paragraphs exactly right each no more than
  2 points below round 7; clean paragraphs untouched at least 95%
- eval: writing problems caught no more than 1 below round 7; voice choices not lower; nothing invented
- human passages, blind: fewer harmful changes than round 7, meaning lost not higher, unnecessary
  changes no more than 2 higher
- blind paragraph revisions: meaning kept on all 40; errors fixed no more than 0.1 lower

## Sealed test
`data/sealed_test` (150 MICUSP paragraphs, 63 planted mistakes, sha256 in `sealed_test.json`) is scored
once, after the decision above, for both round 7 and the selected model, and reported as is. It is not
used to choose or tune anything.
