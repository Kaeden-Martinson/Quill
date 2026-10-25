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

## Results (editor-dev looked at first; editor-holdout opened once, 2026-10-25 02:49)
False-positive rate on real student essays, with Wilson 95% intervals (detector's own threshold):

| Set | Version | Desklib | OpenAI RoBERTa | Fast-DetectGPT |
|---|---|---|---|---|
| editor-dev (200) | original | 4.5% [2.4-8.3] | 1.5% [0.5-4.3] | 16.5% [12.0-22.3] |
| | everything | 22.0% | 21.0% | 31.5% |
| | accept-all fixes | 19.5% [14.6-25.5] | 19.0% [14.2-25.0] | 30.5% |
| | typos mode | 8.5% [5.4-13.2] | 3.5% [1.7-7.0] | 19.5% [14.6-25.5] |
| **editor-holdout (300)** | original | 4.7% [2.8-7.7] | 4.0% [2.3-6.9] | 17.0% [13.2-21.7] |
| | everything | 20.0% [15.9-24.9] | 21.0% [16.8-26.0] | 32.0% [27.0-37.5] |
| | accept-all fixes | 17.7% [13.8-22.4] | 20.0% [15.9-24.9] | 29.3% [24.5-34.7] |
| | typos mode | **9.3%** [6.5-13.2] | **10.7%** [7.7-14.7] | 20.3% [16.2-25.2] |

Against the target (below 20% after editing), on the held-out set:
- typos mode: met confidently for Desklib and OpenAI RoBERTa (whole interval under 20%); not met for
  Fast-DetectGPT (20.3%, which flags 17.0% of unedited essays; editing adds 3.3 points).
- accept-all fixes: Desklib 17.7% below 20% as a point estimate only (interval to 22.4%); OpenAI 20.0%
  and Fast-DetectGPT 29.3% not met.
- Excluding rewrites from bulk accept lowers every detector a little (20.0 -> 17.7, 21.0 -> 20.0,
  32.0 -> 29.3) with no loss of fixes on the benchmarks.
- Every piece rebuilds the editor's text exactly on all 500 new essays (0 mismatches).

Reading: correcting genuine grammar errors is what raises these detectors' false positives. Quill
won't leave errors in to avoid that; it shows writers the trade-off as a choice of mode.
