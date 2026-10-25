"""Local, open-weight AI-text detectors on the detector-track texts (plan.md section 7). Nothing leaves
this machine; only model weights are downloaded (Hugging Face).

    set QUILL_GEN_UNSEAL=1
    .venv-train\\Scripts\\python training\\generation_eval\\run_local_detectors.py [desklib openai-roberta fast-detectgpt]

Runs in the training environment (.venv-train: PyTorch with CUDA, transformers); nothing is installed.
The user's choices (ZeroGPT, GPTZero, QuillBot) are hosted services with no downloadable model, and
sending the licensed student essays to services that keep submissions isn't permitted (sources.json),
so these local detectors stand in:

- desklib: desklib/ai-text-detector-v1.01 (DeBERTa-v3-large fine-tuned on RAID; MIT). Model card's
  code: mean pooling, one-logit head, sigmoid; AI if probability >= 0.5; 768 tokens.
- openai-roberta: openai-community/roberta-base-openai-detector (GPT-2 output detector; MIT). A dated
  baseline: its card says it isn't reliable on ChatGPT-era text. Score = probability of its "Fake"
  label; AI if >= 0.5; 512 tokens.
- fast-detectgpt: Fast-DetectGPT (Bao et al., ICLR 2024; MIT), sampling-discrepancy criterion with
  EleutherAI/gpt-neo-2.7B as both sampling and scoring model (the pair that fits 8 GB), converted to a
  probability with the authors' published normal fits for that pair (local_infer.py), equal priors;
  AI if >= 0.5; 2,048 tokens. The authors rank this pair below falcon-7b and llama3-8b pairs.

Texts scored (and nothing else): human controls (original), the same essays after Quill's editor
(pipeline C), and the baseline Quill drafts of runs baseline-dev, persuade-dev and eval-baseline
(pipelines A and B), excluding drafts left out by plan.md Amendment 1. Experiment variants are never
detector-scored (plan.md section 0). Writes data/generation_eval/detectors/raw/<detector>.csv
(id, group, score, label, error) and <detector>-run.json (model, revision, device, timings), for
detectors.py ingest.
"""
import csv
import json
import math
import sys
import time
from pathlib import Path

import torch
from torch import nn

from common import CORPUS, DETECT, HUMAN, read_jsonl, require_unsealed
import prompts as P

BASELINE_RUNS = ("baseline-dev", "persuade-dev", "eval-baseline")
RAW = DETECT / "raw"
FAST_PARAMS = {"mu0": -0.2489, "sigma0": 0.9968, "mu1": 1.8983, "sigma1": 1.9935}   # gpt-neo-2.7B_gpt-neo-2.7B


def texts():
    """(id, group, text) for every text the detector track scores."""
    require_unsealed("eval", "run_local_detectors.py (human eval essays and eval-baseline drafts)")
    ps = {p["id"]: p for split in ("dev", "eval") for p in P.load(split)}
    out = []
    for name in ("persuade", "ellipse"):
        out += [(r["human_id"], "human", r["text"]) for r in read_jsonl(HUMAN / f"{name}.jsonl")]
    for split in ("dev", "eval"):
        out += [(r["human_id"], "human-C", r["text"]) for r in read_jsonl(HUMAN / f"{split}-C.jsonl")]
    for run in BASELINE_RUNS:
        for pipeline in ("A", "B"):
            for r in read_jsonl(CORPUS / run / f"{pipeline}.jsonl"):
                if r.get("text") and not P.excluded_from_comparison(ps.get(r["prompt_id"], {})):
                    out.append((r["sample_id"], f"quill-{pipeline}", r["text"]))
    return out


def revision(model_id):
    from huggingface_hub import HfApi
    try:
        return HfApi().model_info(model_id).sha
    except Exception as exc:   # recorded, not fatal
        return f"unknown ({type(exc).__name__})"


class Desklib:
    model_id = "desklib/ai-text-detector-v1.01"

    def __init__(self, device):
        from transformers import AutoConfig, AutoModel, AutoTokenizer, PreTrainedModel

        class DesklibAIDetectionModel(PreTrainedModel):   # as on the model card
            config_class = AutoConfig

            def __init__(self, config):
                super().__init__(config)
                self.model = AutoModel.from_config(config)
                self.classifier = nn.Linear(config.hidden_size, 1)
                self.post_init()

            def forward(self, input_ids, attention_mask=None):
                hidden = self.model(input_ids, attention_mask=attention_mask)[0]
                mask = attention_mask.unsqueeze(-1).expand(hidden.size()).float()
                pooled = torch.sum(hidden * mask, 1) / torch.clamp(mask.sum(1), min=1e-9)
                return self.classifier(pooled)

        self.tok = AutoTokenizer.from_pretrained(self.model_id)
        self.model, info = DesklibAIDetectionModel.from_pretrained(self.model_id, output_loading_info=True)
        missing = [k for k in info.get("missing_keys", []) if "position_ids" not in k]
        if missing:
            raise SystemExit(f"desklib weights didn't load cleanly: missing {missing[:5]}")
        self.model.to(device).eval()
        self.device = device

    def score(self, text):
        enc = self.tok(text, padding="max_length", truncation=True, max_length=768, return_tensors="pt").to(self.device)
        with torch.no_grad():
            return torch.sigmoid(self.model(enc["input_ids"], enc["attention_mask"])).item()


class OpenAIRoberta:
    model_id = "openai-community/roberta-base-openai-detector"

    def __init__(self, device):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(self.model_id)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.model_id).to(device).eval()
        labels = {v.lower(): int(k) for k, v in self.model.config.id2label.items()}
        if "fake" not in labels:
            raise SystemExit(f"unexpected labels {self.model.config.id2label}")
        self.fake = labels["fake"]
        self.device = device

    def score(self, text):
        enc = self.tok(text, truncation=True, max_length=512, return_tensors="pt").to(self.device)
        with torch.no_grad():
            return torch.softmax(self.model(**enc).logits, -1)[0, self.fake].item()


class FastDetectGPT:
    model_id = "EleutherAI/gpt-neo-2.7B"

    def __init__(self, device):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(self.model_id)
        dtype = torch.float16 if device == "cuda" else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(self.model_id, torch_dtype=dtype).to(device).eval()
        self.device = device

    @staticmethod
    def criterion(logits_ref, logits_score, labels, chunk=256):
        """Sampling discrepancy, analytic form (Bao et al.; fast_detect_gpt.py, MIT).

        Computed over slices of `chunk` token positions and summed, which gives the same value as the
        whole-sequence formula: on long essays the full-vocabulary float32 tables otherwise filled the
        8 GB GPU and spilled into shared memory, about 50 times slower."""
        if logits_ref.size(-1) != logits_score.size(-1):
            v = min(logits_ref.size(-1), logits_score.size(-1))
            logits_ref, logits_score = logits_ref[..., :v], logits_score[..., :v]
        ll_sum = mean_sum = var_sum = 0.0
        for s in range(0, labels.size(-1), chunk):
            lprobs = torch.log_softmax(logits_score[:, s:s + chunk].float(), -1)
            probs_ref = torch.softmax(logits_ref[:, s:s + chunk].float(), -1)
            ll = lprobs.gather(-1, labels[:, s:s + chunk].unsqueeze(-1)).squeeze(-1)
            mean_ref = (probs_ref * lprobs).sum(-1)
            var_ref = (probs_ref * lprobs.square()).sum(-1) - mean_ref.square()
            ll_sum, mean_sum, var_sum = ll_sum + ll.sum(-1), mean_sum + mean_ref.sum(-1), var_sum + var_ref.sum(-1)
            del lprobs, probs_ref
        return ((ll_sum - mean_sum) / var_sum.sqrt()).mean().item()

    def score(self, text):
        enc = self.tok(text, truncation=True, max_length=2048, return_tensors="pt").to(self.device)
        labels = enc["input_ids"][:, 1:]
        with torch.no_grad():
            logits = self.model(**enc).logits[:, :-1]
        crit = self.criterion(logits, logits, labels)
        p = FAST_PARAMS
        pdf = lambda x, mu, s: math.exp(-0.5 * ((x - mu) / s) ** 2) / (s * math.sqrt(2 * math.pi))  # noqa: E731
        d0, d1 = pdf(crit, p["mu0"], p["sigma0"]), pdf(crit, p["mu1"], p["sigma1"])
        return d1 / (d0 + d1)


DETECTORS = {"desklib": Desklib, "openai-roberta": OpenAIRoberta, "fast-detectgpt": FastDetectGPT}


def run(name, items):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    started = time.time()
    try:
        det = DETECTORS[name](device)
    except torch.cuda.OutOfMemoryError:
        device = "cpu"
        torch.cuda.empty_cache()
        det = DETECTORS[name](device)
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"{name}.csv"
    if out.exists():
        raise SystemExit(f"{out} exists; this experiment never overwrites results.")
    errors = 0
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "group", "score", "label", "error"])
        for n, (tid, group, text) in enumerate(items, 1):
            try:
                s = det.score(text)
                w.writerow([tid, group, f"{s:.6f}", "ai" if s >= 0.5 else "human", ""])
            except Exception as exc:   # recorded as missing, never dropped
                errors += 1
                w.writerow([tid, group, "", "", f"{type(exc).__name__}: {str(exc)[:200]}"])
            if n % 100 == 0:
                print(f"  [{name}] {n}/{len(items)}", flush=True)
    (RAW / f"{name}-run.json").write_text(json.dumps({
        "detector": name, "model": det.model_id, "revision": revision(det.model_id), "device": device,
        "torch": torch.__version__, "texts": len(items), "errors": errors,
        "seconds": round(time.time() - started), "finished": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1), encoding="utf-8")
    del det
    if device == "cuda":
        torch.cuda.empty_cache()
    print(f"{name}: {len(items)} texts, {errors} errors, {round(time.time() - started)} s on {device}")


if __name__ == "__main__":
    items = texts()
    print(f"{len(items)} texts: " + ", ".join(f"{g} {sum(1 for _, gg, _ in items if gg == g)}"
                                          for g in ("human", "human-C", "quill-A", "quill-B")))
    for name in sys.argv[1:] or list(DETECTORS):
        run(name, items)
