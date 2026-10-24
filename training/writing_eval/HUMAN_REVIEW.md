# Blind human review: round 7 vs round 8 editor

Two or three people, each working alone. Allow about 2 hours per person: 40 short paragraphs, then 28
longer passages (about 16,500 words) with 79 proposed changes.

## Use the r8h sheets

`training/writing_eval/packets/people/r8h-revisions.md` + `.csv` and `r8h-human.md` + `.csv`.

These differ from the `r8-*` sheets the model judges used in two ways, neither touching content:
- A/B is counterbalanced: each model appears as "A" in exactly half the items (in `r8-human`, one model
  was "A" in 20 of 28 passages, which could favour or penalise it through order alone).
- Paragraphs whose two versions are word-for-word identical (35 of 40) say so, so raters give them the
  same ratings and spend their attention on the 5 that differ.

The sheets are local only (they quote licensed text). Give raters only these files. They must not open
`judge_key.json` (it maps A/B to models and is in the git repository) or anything else in the repo.

## Checklist for each rater

- [ ] Work alone; don't discuss items with other raters until everyone has finished.
- [ ] Read the rubric at the top of each `.md` file before starting.
- [ ] For every item, read the original first, then each version or change.
- [ ] Judge against the writer's intent and register. Fixing a real error is good. Rewording correct,
      clear text is "unnecessary" even if it reads nicely. Anything that changes what the writer said,
      claimed or qualified is "harmful". Formal writing isn't wrong for being formal.
- [ ] Fill in the matching `.csv` rows (Excel or Google Sheets is fine). Keep the item and version
      names exactly as they are; don't add or reorder rows.
- [ ] Leave a cell blank if you can't decide. Blanks are reported as missing, never guessed.
- [ ] In the human-passage sheet, the "missed errors" column is optional and slow (it means finding
      errors yourself); fill it only if you're confident.
- [ ] Save the CSVs as `r8h-revisions-<yourname>.csv` and `r8h-human-<yourname>.csv` and send them back.

## What you (the person running the review) do

1. Pick 2-3 raters who write well and don't know which model is which.
2. Send each the four `r8h-*` files and this checklist, and nothing else.
3. When the CSVs come back:

       .venv\Scripts\python training\judge_packets.py import-people r8h-revisions-alex.csv alex
       .venv\Scripts\python training\judge_packets.py import-people r8h-human-alex.csv alex
       .venv\Scripts\python training\judge_packets.py score

`score` prints each rater's coverage (items judged, missing), agreement between each pair of raters
(raw and Cohen's kappa), and results by model under "r8h", separate from the Claude judges' "r8".
