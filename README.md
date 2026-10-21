# Quill

A self-hosted essay editor for family and friends. It suggests edits that keep each writer's own voice, explains every change, and keeps a timestamped history of each draft. The model runs on this laptop's GPU through Ollama, so there are no API keys or per-use costs.

## Run it

1. Make sure Ollama is running and the model is pulled (default `gemma4:e4b`).
2. Copy `quill.env.example` to `quill.env` and set a long `QUILL_PASSCODE`. This is the invite code people need to create an account.
3. Start it: `powershell -File scripts\start-quill.ps1` (logs go to `data\server.log`).
4. Open http://localhost:8000 and create your account.

To start it automatically whenever you sign in to Windows (and restart it if it crashes), run once:
`powershell -File scripts\install-autostart.ps1`. While the server runs it keeps the laptop from sleeping; closing the lid may still sleep it, depending on your power settings.

Settings (in `quill.env`): `QUILL_PASSCODE`, `QUILL_MODEL`, `QUILL_HOST`, `QUILL_OLLAMA_URL`, `QUILL_MAX_CONCURRENT`, `QUILL_DATA_DIR`.

## Design

The interface ("Studio") uses cool neutrals, one ink-blue accent, and hairline borders. All colors are tokens at the top of `frontend/style.css`, defined once for light and once for dark. The theme follows the device setting until someone uses the toggle in the top bar; that choice is remembered per browser. Icons are inline SVG symbols in `frontend/index.html` (no emoji, no icon font). Fonts are bundled in `frontend/fonts/` (Inter for the interface, Source Serif 4 for essay text, both SIL Open Font License), so nothing loads from outside the server.

## Accounts and security

- Each person creates an account with their own password; the invite code is only needed once. Passwords are hashed (scrypt), and sessions last 30 days.
- After 5 wrong passwords for a name (or 10 failures from one address), sign-in is paused for 15 minutes. Someone could use this to lock a person out for 15 minutes, but not to get in.
- Admin tasks run on the laptop only:

  ```powershell
  .venv\Scripts\python backend\manage.py users
  .venv\Scripts\python backend\manage.py reset-password NAME
  .venv\Scripts\python backend\manage.py remove NAME
  .venv\Scripts\python backend\manage.py signout-all
  .venv\Scripts\python backend\manage.py backup
  ```

- If the invite code leaks, change it in `quill.env` and restart. Existing accounts keep working.

## Share it

People outside your Wi-Fi need a tunnel to your laptop. Two easy options:
- **Tailscale** (private): invite each person to your tailnet; they open `http://<laptop-name>:8000`.
- **Cloudflare Tunnel** (public link): `cloudflared tunnel --url http://localhost:8000`. Anyone with the link reaches the sign-in page, so use a strong passcode.

The laptop has to be on, awake, and running the server for others to use it.

## How it works

- **My voice**: users paste 3–5 essays they wrote themselves. `backend/style.py` measures sentence rhythm, contractions, first person, punctuation habits and favorite words, and the model is told to match them.
- **Review**: each paragraph goes to the model, which returns up to 4 quoted edits with reasons (structured JSON). Suggestions stream in paragraph by paragraph and are highlighted in the draft; clicking highlighted text brings up its suggestion. A rule-based checker flags stock phrases instantly. Users accept or reject each one.
- **Big-picture feedback**: comments on thesis, structure, evidence and conclusion, plus a top priority and what to keep. Comments only; it never rewrites the essay.
- **Taking turns**: reviews share the GPU through a fair queue (`QUILL_MAX_CONCURRENT` at a time, default 2). Anyone waiting sees their place in line, and closing the tab leaves the line.
- **Word files**: "Import .docx" makes a new essay from a Word file (5 MB limit); "Download .docx" exports the current draft.
- **Phones**: the layout adapts to small screens, with Review buttons pinned at the bottom.
- **History**: versions save on review, every 2 minutes, and on demand. "Download history" exports them with timestamps.
- **Feedback**: every accept/reject is stored and becomes training data.
- **Backups**: `install-autostart.ps1` also schedules a nightly backup at 3 AM to `data\backups` (last 14 kept).

## Train your own model

QLoRA fine-tuning fits on the RTX 5060 (8GB). One epoch on ~6k examples takes roughly 1–2 hours.

```powershell
python -m venv .venv-train
.\.venv-train\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu128
.\.venv-train\Scripts\pip install -r training\requirements.txt
.\.venv-train\Scripts\python training\build_dataset.py
.\.venv-train\Scripts\python training\train.py
ollama create quill-editor -f training\out\Modelfile
$env:QUILL_MODEL = "quill-editor"   # then restart the server
```

Training data comes from Grammarly's open CoEdIT dataset (human-written edits) plus the suggestions your users accepted. Rerun `build_dataset.py` and `train.py` every so often as feedback builds up.

## Check whether a model is actually better

`training/eval_set.jsonl` has 32 paragraphs: 20 with known problems, 12 that are already fine. Compare models side by side:

```powershell
.venv\Scripts\python training\eval.py gemma4:e4b quill-editor
```

Only switch `QUILL_MODEL` if the new model catches more problems (recall) without rewriting clean paragraphs, misquoting, or inventing facts. Raw outputs are saved in `training/eval_results/` for reading by hand.
