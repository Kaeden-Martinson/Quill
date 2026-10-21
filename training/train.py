"""QLoRA fine-tune on an 8GB GPU, then export a GGUF that Ollama can serve.

    python train.py                     # trains, writes training/out/
    ollama create quill-editor -f out/Modelfile
    set QUILL_MODEL=quill-editor        # then restart the app
"""
import os
from pathlib import Path

from unsloth import FastLanguageModel  # must import before trl/transformers
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer
from unsloth.chat_templates import train_on_responses_only

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
BASE = os.environ.get("QUILL_BASE_MODEL", "unsloth/Qwen3-4B-Instruct-2507")
MAX_LEN = 2048

model, tokenizer = FastLanguageModel.from_pretrained(BASE, max_seq_length=MAX_LEN, load_in_4bit=True)
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    lora_alpha=16,
    lora_dropout=0,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth",
)

data = load_dataset("json", data_files={"train": str(HERE / "data/train.jsonl"), "val": str(HERE / "data/val.jsonl")})
data = data.map(lambda ex: {"text": tokenizer.apply_chat_template(ex["messages"], tokenize=False)})

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=data["train"],
    eval_dataset=data["val"],
    args=SFTConfig(
        output_dir=str(OUT / "checkpoints"),
        dataset_text_field="text",
        max_seq_length=MAX_LEN,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8,
        num_train_epochs=1,
        # Set QUILL_MAX_STEPS=5 for a quick end-to-end smoke test.
        max_steps=int(os.environ.get("QUILL_MAX_STEPS", -1)),
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=100,
        save_steps=200,
        optim="adamw_8bit",
        bf16=True,
        report_to="none",
    ),
)
# Only learn from the assistant's JSON answer, not the repeated system prompt.
# These markers are Qwen's chat template; change them if you switch QUILL_BASE_MODEL to another family.
trainer = train_on_responses_only(
    trainer,
    instruction_part="<|im_start|>user\n",
    response_part="<|im_start|>assistant\n",
)
trainer.train()
print(trainer.evaluate())

model.save_pretrained(OUT / "lora")
tokenizer.save_pretrained(OUT / "lora")
model.save_pretrained_gguf(str(OUT / "gguf"), tokenizer, quantization_method="q4_k_m")

# Unsloth writes the GGUF and a Modelfile (with the right chat template) to a sibling "<dir>_gguf" folder.
gguf = next(OUT.glob("gguf*/*.Q4_K_M.gguf"))
unsloth_modelfile = gguf.parent / "Modelfile"
template = unsloth_modelfile.read_text(encoding="utf-8").split("\n", 1)[1] if unsloth_modelfile.exists() else ""
(OUT / "Modelfile").write_text(
    f"FROM {gguf.resolve()}\n{template}\nPARAMETER temperature 0.3\nPARAMETER num_ctx 4096\n", encoding="utf-8"
)
print(f"Done. Next: ollama create quill-editor -f {OUT / 'Modelfile'}")
