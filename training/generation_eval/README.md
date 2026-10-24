# Generator evaluation

Plan: [plan.md](plan.md) (approved 2026-10-23). Separate from the editor rounds. Local-only data goes to
`data/generation_eval/` (git-ignored): generated corpora, licensed human essays, PERSUADE-derived
prompts, detector exports, rating sheets and their blind keys.

Run everything from the repository root with `.venv\Scripts\python`. Nothing here retries, regenerates,
drops or overwrites results; gaps are recorded and reported. The eval split is locked: any command on it
needs `QUILL_GEN_UNSEAL=1` and is logged to `eval_access_log.jsonl`.

| Step | Command |
|---|---|
| Prompt inventory (Quill genres) | `training\generation_eval\prompts.py build` (already built; `prompts.py check` verifies the lock) |
| PERSUADE prompts (after download) | `training\generation_eval\prompts.py persuade` |
| Baseline generation, pipeline A | `training\generation_eval\generate.py baseline-dev dev` |
| Pipeline B (editor on the drafts) | `training\generation_eval\edit.py drafts baseline-dev` |
| Human controls (after licenses are confirmed in `sources.json`) | `training\generation_eval\human.py ingest persuade FILE.csv` |
| Pipeline C (editor on human essays) | `training\generation_eval\edit.py human data\generation_eval\human\persuade.jsonl persuade` |
| Detector results (after describing the detector in `detectors.json`) | `training\generation_eval\detectors.py ingest NAME results.csv` |
| Rating sheets for people / packets for model judges | `training\generation_eval\ratings.py people baseline-dev q-dev` / `ratings.py judges baseline-dev j-dev` |
| Import and aggregate ratings | `ratings.py import q-dev FILLED.csv alex person`, then `ratings.py aggregate q-dev` |
| Validation (duplicates, malformed rows, labels, split overlap, near-duplicates) | `training\generation_eval\validate.py` |
| Statistical summary and report | `training\generation_eval\report.py dev baseline-dev --ratings q-dev --human-c persuade` |

Tests: `.venv\Scripts\python -m pytest tests\test_generation_stats.py tests\test_generation_eval.py`.

Detector results come in as CSV with columns `id, group, score, label, error` (see `detectors.py`).
Quill-draft detector results are reported only as one aggregate per detector (plan.md section 0).
