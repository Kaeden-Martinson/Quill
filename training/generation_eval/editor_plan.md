# Editor work: localized suggestions and editing modes (2026-10-24)

Written before any detector result on the new editor-dev or editor-holdout essays was seen.

## Problem
With every suggestion applied, Quill's editor raised detector false positives on students' own essays
(eval, 300 essays: Desklib 5.0% -> 17.3%, Fast-DetectGPT 22.3% -> 37.7%, OpenAI RoBERTa 2.3% -> 23.0%).
Diagnosis on the 110 dev essays (`editor_diagnosis.py`): typo, punctuation and capitalization fixes barely
move false positives; correcting many genuine small grammar errors drives the rise; rewording alone
doesn't. Separately, 43% of edits changed 3+ tokens: mostly several fixes bundled into one sentence,
the rest rewording under a reason claiming the wording was unchanged.

## Change (justified on writing quality, not on detectors)
`backend/localize.py` splits suggestions into one edit per change, labelled typo, grammar or rewrite;
"Accept all" takes typo and grammar fixes only; rewrites need their own yes; a "Quill suggests" mode
(typos / typos and grammar / everything, default everything as before). The model, its prompt and
settings are unchanged.

## Quality evidence (editor_modes_quality.py, the editor's planted-mistake benchmarks)
| Policy | held-out fixed / perfect / untouched / extra | confirm fixed / perfect / untouched / extra |
|---|---|---|
| everything (old upper bound) | 96.1 / 94.0 / 98.4 / 0.033 | 93.1 / 94.7 / 98.4 / 0.020 |
| accept-all fixes (new bulk) | 96.1 / 94.7 / 100.0 / 0.027 | 93.1 / 94.7 / 98.4 / 0.020 |
| typos mode | 92.2 / 94.0 / 100.0 / 0.007 | 84.2 / 91.3 / 100.0 / 0.000 |

The new bulk policy loses no fixes. Typos mode is an option for writers who want only mechanical fixes;
it leaves grammar errors, so it is not the default.

## How the detector side effect is measured (fixed now)
- Sets: editor-dev (200 new essays) to look at; editor-holdout (300 new essays) opened once at the end.
- Versions of each essay: original; everything applied; accept-all fixes; typos mode.
- Per detector: false-positive rate with Wilson 95% interval, flips against the original, exact McNemar.
- Target (from the brief): false-positive rate below 20% after editing, per detector. Reported two ways:
  point estimate below 20%, and confidently below 20% (upper 95% bound under 20%). Fast-DetectGPT
  already flags ~22% of unedited essays, so for it the target can't be met by any editor change; the
  measure there is how much editing adds.
- No editor behaviour is chosen from these detector numbers; they are reported as side effects. The
  change above stands or falls on the quality evidence.
