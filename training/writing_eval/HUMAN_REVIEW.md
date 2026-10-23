# Blind human review: round 7 vs round 8 editor

Two or three people, each working alone. About 60-90 minutes per person.

## Materials (local only; they quote licensed text, so they're not in git)

After `judge_packets.py make models` and `judge_packets.py export-people`:

- `training/writing_eval/packets/people/r8-revisions.md` with `r8-revisions.csv`: 40 short paragraphs,
  each shown as written and as edited by two editors, A and B.
- `training/writing_eval/packets/people/r8-human.md` with `r8-human.csv`: real published or student
  passages and every change each editor proposed.

"A" and "B" are shuffled separately for every item. Nothing in the files says which model is which; the
key is in `judge_key.json`, which raters shouldn't open.

## What to do

1. Read the rubric at the top of each `.md` file.
2. For each item, read the original first, then the edits. Fill in the matching rows of the `.csv`
   (Excel or Google Sheets is fine; keep the columns and the item and version names as they are).
3. Judge an edit against the original writer's intent and register: correcting a real error is good;
   rewording correct, clear text is unnecessary even if it reads well; anything that changes what the
   writer said is harmful. Formal writing isn't wrong for being formal.
4. Leave a cell blank if you can't decide. Blanks are reported as missing, never guessed.
5. Don't compare notes with other raters until everyone has finished.

## Turning the sheets into results

    .venv\Scripts\python training\judge_packets.py import-people r8-revisions-filled.csv alex
    .venv\Scripts\python training\judge_packets.py import-people r8-human-filled.csv alex
    .venv\Scripts\python training\judge_packets.py score

`score` prints each rater's coverage (items judged and missing), agreement between every pair of raters
(raw agreement and Cohen's kappa on which version was better, and on each change's verdict), and the
results per model. People's ratings are marked `human_rater: true` and reported apart from the model
judges' (Claude subagents), which are a separate, weaker line of evidence.
