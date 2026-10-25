# Follow-up experiments on the generator (proposed 2026-10-24, awaiting approval; nothing run)

From `dev_findings.md`. Each experiment changes one thing and is judged on quality only, never on
detectors. Decision rules are fixed here, before any result exists.

## Common procedure
- **Baseline:** the existing dev drafts (pipeline A) for the same prompts. Variants reuse each sample's
  seed, so a variant differs from its baseline draft only by the change under test.
- **Fixed:** model (`gemma4:e4b`), Ollama 0.40.4, sampling settings, schema, post-processing, voice
  condition, and every prompt text except the line the experiment changes.
- **Judging:** each experiment's variant drafts and their baseline drafts go into one blind packet with
  counterbalanced order, rated by two model judges with the saved instructions, each in its own working
  folder. Optional: 2-3 people on a subset, reported separately.
- **Scope:** dev prompts only. A change is carried to the locked eval run only if its rule below says
  "adopt"; the eval run then compares the adopted configuration with the baseline once.
- **Statistics:** paired differences (variant minus baseline, per sample, averaged over judges) with a
  cluster bootstrap by prompt; counts compared as paired proportions. Same reporting rules as plan.md 8.

## E1. Writer details first (invented personal details)
- **Question:** if the writer's input already includes the specific details a personal piece needs, does
  the generator stop inventing them? This tests the product idea of having Quill ask the writer for 2-3
  details before drafting personal pieces; the prompt alone has not stopped invention (REPORT.md).
- **One change:** for the personal-experience dev prompts (narrative, application, scholarship, job,
  blog, personal: 8 prompts), the instructions gain three short, concrete details answering the obvious
  questions (a moment, a person, an outcome). The details are written once, before generation, and
  committed with the plan of the run.
- **Samples:** 8 prompts x 3 seeds = 24 variant drafts (the baseline's two seeds plus one new seed per
  prompt, also run for the baseline).
- **Measures:** drafts both judges flag for invented personal details (primary); usefulness, voice,
  adherence.
- **Adopt the product idea** if flagged drafts fall by at least half (e.g. 12/15 -> 6/15 or fewer on
  matched samples) and usefulness is not lower by more than 0.25. **Not supported** if the fall is less
  than a quarter. Otherwise inconclusive. Adopting means proposing the ask-first step in the app as its
  own change.
- **Risk:** writers asked for details may give fewer or vaguer ones than these; this is a best case.

## E2. Length stated as a range (drafts shorter than requested)
- **One change:** the length line in `draft_prompt` changes from "about 500 words" to "about 500 words
  (aim for 450-550)", and likewise for short (225-275) and long (810-990).
- **Samples:** all 33 dev prompts in the comparison, same seeds as the baseline: 106 drafts.
- **Measures:** median length as a share of the target per length band (primary); drafts under 70%;
  repetition, coherence, usefulness.
- **Adopt** if the medium-band median reaches at least 90% of target, drafts under 70% don't increase,
  and repetition, coherence and usefulness are each not lower by more than 0.2. **Not supported** if the
  medium median moves by less than 3 points. Otherwise inconclusive.
- **Risk:** longer drafts padded with repetition; the repetition guard is there to catch it.

## E3. Plan concrete support first (generic substance)
- **One change:** drafting becomes two calls. The first asks for a short private plan: for each of the
  writer's points, one concrete example, case, step or consequence that supports it, using only the
  writer's points and widely established knowledge, with no statistics, studies, quotations or names the
  writer didn't give. The second call is the live drafting request with that plan appended. Everything
  else is unchanged.
- **Samples:** all 33 dev prompts, same seeds: 106 drafts (two calls each).
- **Measures:** specificity and evidence (primary); factual reliability, unsupported claims, invented
  personal details, adherence, usefulness.
- **Adopt** if specificity and evidence each rise by at least 0.3, factual reliability is not lower by
  more than 0.2, unsupported claims and invented details don't increase, and adherence is not lower by
  more than 0.2. **Not supported** if both primary measures move by less than 0.1. Otherwise inconclusive.
- **Risks:** more invented specifics (guarded by the factual and invention measures); roughly double the
  drafting time in the app.

## E4. Scenes allowed in literary analysis (weakest genre)
- **One change:** for literary-analysis prompts, the drafting request adds one sentence: "Refer to
  specific scenes, events and characters' actions from the work; don't quote it unless the writer gave
  the quotation." The general rule against invented quotations stays.
- **Samples:** the 3 literary dev prompts x 5 seeds = 15 variant drafts, with 15 baseline drafts
  (3 new seeds per prompt run for the baseline).
- **Measures:** specificity and evidence on literary drafts (primary); factual reliability (misremembered
  or invented plot events), adherence.
- **Adopt** if specificity rises by at least 0.5 and factual reliability is not lower by more than 0.3
  and stays at 4.0 or above. **Not supported** if specificity moves by less than 0.2. Otherwise
  inconclusive. The sample is small; an adopted result is confirmed on eval.
- **Risk:** the model misremembers the works; judges check plot accuracy.

## D1. Format leak fix (a defect, not an experiment)
In `editor.draft_stream`, drop "paragraphs" that contain no letters or are only JSON or markup debris
(such as `]}<tool_call|>{`), with a unit test from the observed case. It changes the live app, so it
needs separate approval; it doesn't alter any draft that has real paragraphs.

## Suggested order and cost
D1 (minutes, after approval), then E2 (~1 hour), E1 (~20 minutes), E4 (~15 minutes), E3 (~2 hours),
each followed by its judging packet. E2 and E3 touch every prompt, so they are run and judged
separately, never combined in one comparison.

## Approval and eval rules (fixed 2026-10-24, before any follow-up or eval generation)
Approved by the user on 2026-10-24 ("go ahead and fix everything"), including D1 and the eval run.

**Eval run.** After E1-E4 are decided on dev: the baseline configuration on every eval prompt in the
comparison (24 Quill-genre x 2 seeds + 3 PERSUADE x 10 = 78 drafts), pipelines A and B; if E2 and/or E3
are adopted, the adopted configuration (all adopted prompt changes together) on the same prompts and
seeds; pipeline C on the 300 eval human essays (for the detector track). One blind packet per
comparison, two model judges, separate working folders.

**Changing the live drafting prompt.** An adopted change goes into the live app only if, on eval, its
primary measure moves in the same direction as on dev by at least half its dev threshold, and the guards
hold:
- E2: medium-band median share of target at least 5 points above the baseline's.
- E3: specificity and evidence each at least 0.15 above the baseline's.
- Guards (whole eval set): adherence, factual reliability and usefulness each not lower by more than
  0.2; invented personal details and unsupported claims not higher.
- E4 can't be confirmed (the eval set has no literary prompts) and E1 is a product change, not a prompt
  change, so neither is applied to the live app by this experiment; they're reported with their dev
  evidence.
- D1 is a defect fix and goes in regardless, with its unit test.
If nothing passes, the live drafting prompt stays exactly as it is.

## E5. Writer's examples and evidence for non-personal pieces (added 2026-10-24, before generation)
- **Question:** E1 showed writer-supplied details transform personal drafts. Specificity and evidence
  stay about 3/5 across all genres; does giving the drafter the writer's own examples or evidence lift
  them in arguments, explanations and letters too?
- **One change:** for 10 non-personal dev prompts (experiments/e5_examples.json, written before any
  generation), the instructions gain three examples or pieces of evidence, as "Examples and evidence I
  can use:". Everything else as E1.
- **Samples:** 10 prompts x 3 seeds (the baseline's two plus one new, also run for the baseline).
- **Measures:** specificity and evidence (primary); factual reliability, unsupported claims, adherence,
  usefulness, voice.
- **Adopt** (as an optional "Examples or evidence to use" field in the draft dialog) if specificity and
  evidence each rise by at least 0.3, factual reliability is not lower by more than 0.2, adherence is not
  lower by more than 0.2, and unsupported claims don't increase. **Not supported** if both primary
  measures move by less than 0.1. Otherwise inconclusive.
- Judged on quality only by two blind model judges, variant and baseline in one packet; no detector
  scoring of variants (plan.md section 0).
