"""Prompt and decoding configurations for the writing experiments.

"original" mirrors the live app exactly; candidates sit beside it so they can be measured before
anything changes in the app. compare_writing.py runs drafts and revisions under these;
reliability.py and eval.py score the editor under one when QUILL_PROMPT_CONFIG names it.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import editor  # noqa: E402
from config import EDIT_OPTIONS  # noqa: E402

NO_VOICE = "No writing samples yet; keep the writer's existing tone."  # style.describe_voice({})


# ---------------------------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------------------------

# The drafting prompt and settings live before 2026-10-22 ("original" in REPORT.md), kept verbatim so
# the comparison can be re-run. The tested replacement ("improved") is now the live one in editor.py.
DRAFT_SYSTEM_V1 = """You write a first draft of an essay from the writer's instructions, in the voice described.
Follow the voice closely: sentence length, contractions, first person, formality.
Stay on the writer's topic and points. Never invent statistics, quotes, studies, or personal
events that the writer didn't mention; where the essay needs a specific detail only the writer
knows, write a short bracketed placeholder like [your example here] instead.
Write plain paragraphs, no headings or lists. "title" is a short working title."""

DRAFT_LENGTHS_V1 = {"short": "about 250 words (3 paragraphs)", "medium": "about 500 words (5 paragraphs)",
                    "long": "about 900 words (7 paragraphs)"}
DRAFT_OPTIONS_V1 = {"temperature": 0.75, "top_p": 0.9, "repeat_penalty": 1.1}


def draft_prompt_v1(instructions, voice, sample=None, goal="", audience="", tone="", length="medium"):
    parts = [f"Writer's voice:\n{voice}"]
    if sample:
        parts.append(f"A sample of how this writer sounds (match the style, not the content):\n\"\"\"\n{sample}\n\"\"\"")
    for label, value in (("Essay goal", goal), ("Audience", audience), ("Tone", tone)):
        if value:
            parts.append(f"{label}: {value}")
    parts.append(f"Length: {DRAFT_LENGTHS_V1.get(length, DRAFT_LENGTHS_V1['medium'])}")
    parts.append(f"Instructions:\n\"\"\"\n{instructions}\n\"\"\"")
    return "\n\n".join(parts)


DRAFT_SYSTEM_V2 = editor.DRAFT_SYSTEM
DRAFT_LENGTHS_V2 = editor.DRAFT_LENGTHS
draft_prompt_v2 = editor.draft_prompt


# repeat_penalty pushes the model off every token it has already used, including the topic's own
# key words, which can force synonym-swapping ("the library... the facility... this institution").
# min_p trims the unlikely tail relative to the top word, so variety comes from plausible words.
DRAFT_OPTIONS_V2 = {"temperature": 0.8, "top_p": 1.0, "min_p": 0.05, "repeat_penalty": 1.0}


# ---------------------------------------------------------------------------------------------
# Revision
# ---------------------------------------------------------------------------------------------
# The line editor (quill-editor-v7) is fine-tuned with editor.SYSTEM in every example, so this
# prompt at inference is off its training distribution. It's the target for the next training
# round; testing it on v7 now shows whether instructions alone move the model.

EDIT_SYSTEM_V2 = """You are an editor marking up one paragraph of someone else's essay. Make it work better as
their writing, not as yours. The request names one editing mode; stay inside its scope.

Modes:
- proofread: errors only. Grammar, spelling, punctuation, and wrong words (their/there, its/it's,
  could of). Change nothing that isn't an error.
- clarity: proofread, plus sentences a reader would misunderstand or have to read twice: an
  unclear pronoun, a missing word, a tangle that hides the meaning. Fix them with the smallest
  change that makes the meaning clear, in the writer's own words.
- structure: clarity, plus how the sentences connect: a jump between ideas, a missing link, a
  run-on that should be two sentences, a sentence that belongs earlier. Rearrange and connect;
  don't add new ideas.
- substance: the thinking, not the wording: a claim with no support, a reason that doesn't
  follow, a missing step, an example that doesn't show what it's meant to. Don't write the
  argument for them. Quote the sentence, keep "revised" identical to it, and use "reason" to say
  what's missing so the writer can supply it.

In every mode, keep:
- The writer's words, rhythm and register: contractions, slang they mean, deliberate fragments,
  repetition for effect, and unusual phrasing that works.
- Their meaning, opinions, evidence and claims, even ones you'd argue with.

In every mode, never:
- Replace an ordinary word with a fancier synonym, or make casual writing formal.
- Add facts, examples, statistics, sources, quotations or personal details.
- Rewrite a sentence that is correct and clear just to polish it.

Format: at most 4 edits. "original" is an exact, contiguous quote from the paragraph; "revised"
replaces only that quote. "reason" is one short sentence naming the specific problem here, not
a general rule. No edits at all is the right answer for a paragraph that works."""

EDIT_MODES = ("proofread", "clarity", "structure", "substance")


def review_prompt(paragraph, voice, goal):
    # The exact shape the fine-tuned editor was trained on (editor.review_paragraph).
    return f"Writer's voice:\n{voice}\n\nEssay goal: {goal or 'not specified'}\n\nParagraph:\n\"\"\"\n{paragraph}\n\"\"\""


def review_prompt_mode(mode):
    def build(paragraph, voice, goal):
        return (f"Editing mode: {mode}\n\nWriter's voice:\n{voice}\n\nEssay goal: {goal or 'not specified'}\n\n"
                f"Paragraph:\n\"\"\"\n{paragraph}\n\"\"\"")
    return build


# ---------------------------------------------------------------------------------------------

# Blind judging found every configuration inventing memories, scenes and dialogue in personal
# pieces (honesty 2.2-2.8 of 5 on those), with the "never invent" instruction ignored. This variant
# changes one thing: it makes leaving gaps the explicit job for anything only the writer knows.
DRAFT_SYSTEM_V3 = DRAFT_SYSTEM_V2 + """

Personal material (this overrides everything above where they conflict):
The writer's memories, feelings, people, places and words are theirs, and you only know what the
instructions say. When a piece needs one you weren't given, do not write it, even plausibly, even
briefly. Write the sentence around it and put a bracketed question in its place, specific enough to
answer: [What exactly did they say to you?] [Where were you when this happened?] A personal piece
will usually need several. A draft with honest gaps the writer fills in is the goal; a smooth draft
built on made-up memories is a failure, because the writer would be submitting someone else's life."""

DRAFT_CONFIGS = {
    "original": {"system": DRAFT_SYSTEM_V1, "prompt": draft_prompt_v1, "options": DRAFT_OPTIONS_V1},
    # New prompt, live decoding: isolates what the prompt alone changes.
    "prompt-only": {"system": DRAFT_SYSTEM_V2, "prompt": draft_prompt_v2, "options": DRAFT_OPTIONS_V1},
    # New prompt and new decoding.
    "improved": {"system": DRAFT_SYSTEM_V2, "prompt": draft_prompt_v2, "options": DRAFT_OPTIONS_V2},
    # "improved" plus the personal-material rule only.
    "scaffold": {"system": DRAFT_SYSTEM_V3, "prompt": draft_prompt_v2, "options": DRAFT_OPTIONS_V2},
}

REVISE_CONFIGS = {
    "original": {"system": editor.SYSTEM, "prompt": review_prompt, "options": EDIT_OPTIONS},
    "v2-proofread": {"system": EDIT_SYSTEM_V2, "prompt": review_prompt_mode("proofread"), "options": EDIT_OPTIONS},
    "v2-clarity": {"system": EDIT_SYSTEM_V2, "prompt": review_prompt_mode("clarity"), "options": EDIT_OPTIONS},
}


def editor_request(paragraph, voice, goal):
    """(system, user) for one editor call under QUILL_PROMPT_CONFIG (default: the live prompt)."""
    cfg = REVISE_CONFIGS[os.environ.get("QUILL_PROMPT_CONFIG") or "original"]
    return cfg["system"], cfg["prompt"](paragraph, voice, goal)


def describe(name, kind):
    """The exact configuration as plain data, saved beside each run for reproducibility."""
    cfg = (DRAFT_CONFIGS if kind == "draft" else REVISE_CONFIGS)[name]
    sample_prompt = cfg["prompt"]("<instructions>", "<voice>", None, "<goal>", "<audience>", "", "medium") \
        if kind == "draft" else cfg["prompt"]("<paragraph>", "<voice>", "<goal>")
    return {"name": name, "kind": kind, "system": cfg["system"], "user_prompt_template": sample_prompt,
            "options": cfg["options"],
            "model": editor.OVERVIEW_MODEL if kind == "draft" else editor.MODEL}
