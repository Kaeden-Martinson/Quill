# Polish evaluation plan (written 2026-10-25, before any polish output was generated)

Polish (`editor.polish_stream`, `/api/polish`) rewrites each paragraph for grammar and flow and keeps
the writer's ideas and content. The writer takes or rejects each paragraph, and taken paragraphs are
recorded as AI-written. This plan fixes how it is judged before it runs.

## Sample
- 40 essays from **editor-dev**, drawn with seed 20261025 (`polish_eval.py sample`). The locked
  editor-holdout set is not used. It was opened once for the editor and stays closed.
- Each essay is polished whole with the app's own call: the voice is measured from the essay for a
  writer with no profile, the goal is "not specified", and the generator and settings are
  `POLISH_OPTIONS`. Every polished paragraph is taken. That is an upper bound, since writers choose
  paragraph by paragraph.
- Comparison: the same essays through the line editor with every suggestion applied
  (`editor-dev-C.jsonl`, already on disk, "Everything" in editor_plan.md).

## Measures
1. **Model-judge ratings (not human ratings).** Two blind Claude judges each see the original and the
   two revisions, labelled X and Y in a random order per essay. Each judge rates each revision 1–5 on:
   - **meaning**: every claim, example, reason and detail is kept, and nothing is added;
   - **errors**: spelling, grammar and punctuation are fixed;
   - **flow**: reads smoothly, with clear sentences and transitions;
   - **voice**: still sounds like this student (vocabulary, tone, level), not like a polished adult
     writer;
   - **restraint**: changes only what needed changing.
2. **Content check** (`polish.check`): the share of paragraphs with each warning, the mean share of
   key words kept, and the length change. Whether judge-rated meaning losses (meaning ≤ 2) carry a
   warning tells us if the check catches real problems.
3. **Detectors**: Desklib, OpenAI RoBERTa and Fast-DetectGPT flag rates for original / editor /
   polish. These are a **diagnostic only**: polish is AI-written text and is expected to be flagged
   far more. Nothing is tuned against them.

## Decision rules (fixed now)
- **Ship as built** if all of the following hold (means over both judges and all 40 essays):
  - polish meaning ≥ 4.0, and no more than 10% of essays get meaning ≤ 2 from either judge;
  - polish errors ≥ editor errors − 0.25 (fixes about as much as the line editor);
  - polish flow > editor flow (the reason Polish exists);
  - polish voice ≥ 3.0.
- **If meaning or voice fails:** Polish ships only after a prompt or check change, re-evaluated on
  40 *different* editor-dev essays, with this report showing both runs.
- **If flow does not beat the editor:** Polish adds nothing over the line editor and is not shipped.
- Results are reported as written, including failures.

## Results (2026-10-25)

40 editor-dev essays (253 paragraphs), gemma4:e4b, Ollama 0.40.4. Ratings come from two blind Claude
judges (model judgments, **not human ratings**). The judges are the same model and agree closely
(mean gap 0.1–0.2 points; every rating within 1), so they are not two independent raters.

| Mean (1–5) | Line editor, everything | Polish, every paragraph |
|---|---|---|
| meaning | 4.38 | 4.35 |
| errors | 2.92 | **4.55** |
| flow | 3.08 | **4.46** |
| voice | **4.89** | 4.05 |
| restraint | **4.26** | 3.60 |

Both judges rated Polish higher on errors for 38 of 40 essays and on flow for 35 (the editor was
never higher on either). They rated the editor higher on voice for 27 and on restraint for 17
(Polish was higher on restraint once). Meaning was split: Polish higher on 9, the editor on 10.

**Decision rules:** all five pass (meaning 4.35 ≥ 4.0; meaning ≤ 2 on 1 of 40 essays; errors 4.55 ≥
2.67; flow 4.46 > 3.08; voice 4.05 ≥ 3.0). **Polish ships as built**, with one fix:

- **The failure (e05):** one essay with a single 1,137-word paragraph came back with its last ~190
  words gone. The model ran out of room, and the content check did not warn: −17% length is under
  the 30% threshold, and repeated words kept the key-word share at 0.90.
  - The output cap went from 2,048 to 4,096 tokens. On a rerun the model still stopped early (512
    words).
  - So paragraphs of 375+ words are now polished in sentence-aligned pieces of about 250 words
    (`polish.pieces`). Rerun: 1,139 words, the ending intact, no warnings.
  - The check also gained a cut-off warning: the polish stops mid-sentence, or none of the original's
    last sentence is near its end, with loose word matching so corrected misspellings still count.
    On the 253 paragraphs it fires only on e05.
  - No other paragraph in the sample reaches 375 words, so the other 39 essays' results are
    unaffected.
- **Content check:** 13% of paragraphs carried a warning (names 5.5%, quotations 3.6%, wording 2.8%,
  numbers 1.2%, length 0.8%). Mean key words kept 0.91; mean length change −2.5%. Before the cut-off
  warning, it missed the one low-meaning essay (e05).

**Detectors (diagnostic only, nothing tuned):** share of the 40 essays flagged as AI.

| | Original | Line editor, everything | Polish, every paragraph |
|---|---|---|---|
| Desklib | 2.5% | 22.5% | 50.0% |
| OpenAI RoBERTa | 0.0% | 17.5% | 32.5% |
| Fast-DetectGPT | 12.5% | 20.0% | 30.0% |

As expected, polished essays are flagged as AI far more often. That is why the app records every
paragraph the writer takes as AI-written.
