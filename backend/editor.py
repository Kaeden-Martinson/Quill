"""Asks the local model (via Ollama) for paragraph edits and big-picture feedback.

Reviews take turns through a fair queue: each review holds one slot and works through its
paragraphs in order, so one long essay can't starve everyone else on a single laptop GPU.
"""
import asyncio
import itertools
import json
import re
from collections import deque

import httpx

import rules
from config import (DRAFT_OPTIONS, EDIT_OPTIONS, LETTER_OPTIONS, MAX_CONCURRENT_REVIEWS, MODEL, OLLAMA_URL,
                    OVERVIEW_MODEL)

CATEGORIES = ["clarity", "flow", "argument", "evidence", "concision", "grammar", "word choice"]

SUGGESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": {"type": "string"},
                    "revised": {"type": "string"},
                    "reason": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                },
                "required": ["original", "revised", "reason", "category"],
            },
        }
    },
    "required": ["suggestions"],
}

SYSTEM = """You are a writing coach who edits essays while preserving the writer's own voice.
Rules:
- Suggest at most 4 targeted edits for the paragraph. Fewer is fine; none if it's already strong.
- "original" must be an exact, contiguous quote from the paragraph (a phrase or one sentence).
- "revised" replaces only that quote. Keep the writer's vocabulary, rhythm, and tone.
- Never add facts, statistics, or sources the writer didn't provide. If evidence is weak,
  say so in "reason" and keep "revised" close to the original.
- Never use stock phrases like "delve", "tapestry", "it is important to note", "in today's world".
- "reason" is one short sentence teaching why the change helps."""

OVERVIEW_ASPECTS = ["thesis", "structure", "evidence", "conclusion"]

OVERVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "strongest_part": {"type": "string"},
        "top_priority": {"type": "string"},
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "aspect": {"type": "string", "enum": OVERVIEW_ASPECTS},
                    "rating": {"type": "string", "enum": ["strong", "okay", "needs work"]},
                    "comment": {"type": "string"},
                },
                "required": ["aspect", "rating", "comment"],
            },
        },
    },
    "required": ["strongest_part", "top_priority", "comments"],
}

OVERVIEW_SYSTEM = """You are a writing teacher giving big-picture feedback on a whole essay.
Comment on thesis, structure, evidence, and conclusion: one comment each, two or three sentences,
specific to this essay (refer to its actual paragraphs and ideas).
Do not rewrite the essay or supply sentences for it; explain what to work on and why, so the
writer can revise it themselves. Never invent facts about the topic.
"strongest_part" names what already works, so the writer keeps it.
"top_priority" is the single change that would improve the essay most."""


class FairQueue:
    """FIFO line for model access with a fixed number of slots."""

    def __init__(self, slots):
        self.slots = slots
        self.active = 0
        self.waiting = deque()
        self.changed = asyncio.Condition()
        self.ids = itertools.count()

    def join(self):
        ticket = next(self.ids)
        self.waiting.append(ticket)
        return ticket

    async def try_start(self, ticket):
        """Returns 0 if the ticket now holds a slot, else its place in line (1 = next)."""
        async with self.changed:
            if self.waiting[0] == ticket and self.active < self.slots:
                self.waiting.popleft()
                self.active += 1
                self.changed.notify_all()
                return 0
            return self.waiting.index(ticket) + 1

    async def wait_for_change(self, timeout=5):
        async with self.changed:
            try:
                await asyncio.wait_for(self.changed.wait(), timeout)
            except asyncio.TimeoutError:
                pass

    async def leave(self, ticket, started):
        async with self.changed:
            if started:
                self.active -= 1
            elif ticket in self.waiting:
                self.waiting.remove(ticket)  # gave up while waiting (closed the tab)
            self.changed.notify_all()


queue = FairQueue(MAX_CONCURRENT_REVIEWS)


async def take_turn(ticket):
    """Yields queue positions until it's this ticket's turn."""
    last = None
    while position := await queue.try_start(ticket):
        if position != last:
            yield position
            last = position
        await queue.wait_for_change()


def split_paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


# Ollama reloads the model whenever num_ctx changes, so sizes come in a few fixed steps.
CONTEXT_STEPS = (4096, 8192, 16384)
RESPONSE_RESERVE = 2048  # room for the model's JSON answer


def estimate_tokens(text):
    # About 4 characters per token for English; 3 is deliberately pessimistic.
    return len(text) // 3 + 1


def context_size(*texts):
    """Smallest step that fits the prompt plus the answer, or None if nothing does."""
    needed = sum(estimate_tokens(t) for t in texts) + RESPONSE_RESERVE
    return next((step for step in CONTEXT_STEPS if needed <= step), None)


def fit_paragraphs(paragraphs, *fixed_texts):
    """Keeps as many leading paragraphs as fit in the largest context step."""
    budget = CONTEXT_STEPS[-1] - RESPONSE_RESERVE - sum(estimate_tokens(t) for t in fixed_texts)
    kept, used = [], 0
    for p in paragraphs:
        used += estimate_tokens(p) + 1
        if used > budget:
            break
        kept.append(p)
    return kept


def parse_reply(content):
    """The JSON object in a model reply, ignoring anything before it.

    Ollama's format constraint isn't always honored (the fine-tuned model can emit a special token
    such as a stray end-of-thinking marker first), so parse from the first "{" rather than failing.
    """
    start = content.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(content[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


async def chat(client, system, prompt, schema, model=MODEL, options=EDIT_OPTIONS):
    num_ctx = context_size(system, prompt) or CONTEXT_STEPS[-1]
    resp = await client.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            "options": {**options, "num_ctx": num_ctx},
        },
        timeout=300,
    )
    resp.raise_for_status()
    try:
        return parse_reply(resp.json()["message"]["content"])
    except KeyError:
        return None


async def review_paragraph(client, paragraph, voice, goal):
    prompt = (
        f"Writer's voice:\n{voice}\n\n"
        f"Essay goal: {goal or 'not specified'}\n\n"
        f"Paragraph:\n\"\"\"\n{paragraph}\n\"\"\""
    )
    result = await chat(client, SYSTEM, prompt, SUGGESTION_SCHEMA)
    items = (result or {}).get("suggestions", [])
    # Drop anything the model didn't actually quote or didn't change.
    kept = [
        s for s in items
        if isinstance(s, dict) and isinstance(s.get("original"), str) and s["original"] in paragraph and s.get("revised") != s["original"]
    ]
    # Then add the near-certain mechanical fixes the model missed ("Its weird how...").
    return rules.apply(paragraph, kept)


async def review_stream(text, voice, goal=""):
    """Yields events: queue, start, paragraph (one per paragraph), done."""
    paragraphs = split_paragraphs(text)
    ticket, started = queue.join(), False
    try:
        async for position in take_turn(ticket):
            yield {"type": "queue", "position": position}
        started = True
        yield {"type": "start", "total": len(paragraphs)}
        async with httpx.AsyncClient() as client:
            for i, paragraph in enumerate(paragraphs):
                suggestions = await review_paragraph(client, paragraph, voice, goal)
                yield {"type": "paragraph", "index": i, "total": len(paragraphs), "suggestions": suggestions}
        yield {"type": "done"}
    finally:
        await queue.leave(ticket, started)


async def overview_stream(text, voice, goal=""):
    """Yields events: queue, start, notice (only if the essay was too long), overview, done."""
    ticket, started = queue.join(), False
    try:
        async for position in take_turn(ticket):
            yield {"type": "queue", "position": position}
        started = True
        yield {"type": "start", "total": 1}
        header = f"Writer's voice:\n{voice}\n\nEssay goal: {goal or 'not specified'}\n\nEssay:\n"
        paragraphs = split_paragraphs(text)
        kept = fit_paragraphs(paragraphs, OVERVIEW_SYSTEM, header)
        if len(kept) < len(paragraphs):
            # Say so rather than silently judging an essay without its ending.
            yield {"type": "notice", "message": (
                f"This essay is longer than the model can read at once, so this feedback covers "
                f"the first {len(kept)} of {len(paragraphs)} paragraphs."
            )}
        prompt = header + '"""\n' + "\n\n".join(kept) + '\n"""'
        async with httpx.AsyncClient() as client:
            result = await chat(client, OVERVIEW_SYSTEM, prompt, OVERVIEW_SCHEMA, model=OVERVIEW_MODEL, options=LETTER_OPTIONS)
        yield {"type": "overview", "overview": result}
        yield {"type": "done"}
    finally:
        await queue.leave(ticket, started)


DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "paragraphs"],
}

# The drafting prompt tested as "improved" in training/writing_eval/REPORT.md. Its predecessor asked
# for a fixed paragraph count and, with no voice chosen, to keep the tone of text that didn't exist;
# drafts came out as one template (61% ended on "Ultimately" or "In conclusion", no human sample did).
# The old prompt stays in training/prompt_candidates.py so that comparison can be re-run.
DRAFT_SYSTEM = """You write a first draft that the writer will revise and finish themselves. It should do the
specific job their assignment asks for, built from the points they gave you.

Before writing, decide privately: what kind of piece this is (argument, narrative, analysis,
explanation, letter, review, how-to...), who reads it, and the one thing it has to get across.
Let that decide the structure. An argument might lead with its claim and spend most of its length
on the hardest objection; a narrative might stay inside one scene; an explanation might follow
the order things happen. Use as many paragraphs as the material needs, not a set number, and let
them differ in length.

Substance:
- Build from the writer's own points. Give each one its reasoning: why it holds, what follows
  from it, where it stops holding. Developing two points well beats listing four.
- Prefer the concrete: a particular moment, object, step or consequence over a general claim.
  A general claim should be followed by something specific that earns it.
- For arguments, take the strongest objection seriously and answer it or concede part of it.
- Background facts must be widely established and stated no more precisely than you can stand
  behind. No statistics, dates, studies, quotations, sources or names the writer didn't give.
- Never invent the writer's experiences, feelings, people or events. Where the piece needs one,
  write a bracketed note saying what belongs there, e.g. [the moment you realized it was working].

Openings and endings:
- Start with the substance: the claim, the scene, the question the piece answers. Don't restate
  the assignment, define terms nobody asked about, or open on a sweeping statement about society.
- End on something that moves past the body: a consequence, a sharper version of the claim, a
  final concrete image, what the writer will do next. Don't summarize the paragraphs or announce
  the ending ("In conclusion", "Ultimately", "Overall", "In the end").

Language:
- Plain, exact words. If an ordinary word says it, use it. Repeating the right word is better
  than swapping in synonyms to avoid repetition.
- Let the logic connect the ideas; use a transition word only where the relationship (contrast,
  cause, sequence) would otherwise be unclear.
- Avoid filler patterns: "not just X, it's Y", lists of three by habit, stacked adjectives,
  opening rhetorical questions, and words like delve, crucial, vital, pivotal, journey, navigate,
  landscape, testament, foster, profound.
- Let sentence length follow the thought, not a pattern.

Voice:
- If a voice or a writing sample is given, match it: sentence length, contractions, first
  person, formality, humor.
- If no voice is given, you know nothing about this writer's personal style, so don't invent
  one. Write in clear, natural language suited to the assignment and its reader. Don't add a
  personality, quirks, slang, jokes, or details about the writer's life.

Return plain paragraphs, no headings or lists. "title" is a short, specific working title."""

DRAFT_LENGTHS = {"short": "about 250 words", "medium": "about 500 words", "long": "about 900 words"}
NO_VOICE = "No writing samples yet; keep the writer's existing tone."  # style.describe_voice({})


def draft_prompt(instructions, voice, sample=None, goal="", audience="", tone="", length="medium"):
    """Length in words only (a paragraph count made every draft the same shape), and when no voice
    was chosen it says so, instead of asking to keep the tone of text that doesn't exist yet."""
    if voice.strip() == NO_VOICE:
        voice = "Not given."
    parts = [f"Writer's voice:\n{voice}"]
    if sample:
        parts.append(f"A sample of how this writer sounds (match the style, not the content):\n\"\"\"\n{sample}\n\"\"\"")
    for label, value in (("What it's for", goal), ("Who reads it", audience), ("Tone", tone)):
        if value:
            parts.append(f"{label}: {value}")
    parts.append(f"Length: {DRAFT_LENGTHS.get(length, DRAFT_LENGTHS['medium'])}")
    parts.append(f"The writer's instructions and points:\n\"\"\"\n{instructions}\n\"\"\"")
    return "\n\n".join(parts)


def draft_from_reply(result):
    """(title, body) from the drafter's parsed reply, or (None, None) when there's no draft.

    One array item can hold several paragraphs; their breaks are kept instead of merged. A "paragraph"
    with no words once markup is removed is debris from the model, not text (it once emitted a stray
    `]}<tool_call|>{` as a final paragraph), so it's dropped."""
    paragraphs = [" ".join(q.split()) for p in (result or {}).get("paragraphs", []) if isinstance(p, str)
                  for q in re.split(r"\n\s*\n", p)
                  if re.search(r"[^\W\d_]", re.sub(r"<[^<>]*>", "", q))]
    if not paragraphs:
        return None, None
    title = " ".join(((result or {}).get("title") or "").split())[:200] or "Untitled draft"
    return title, "\n\n".join(paragraphs)


async def draft_stream(prompt):
    """Yields events: queue, start, draft (title and body), done. Uses the general model."""
    ticket, started = queue.join(), False
    try:
        async for position in take_turn(ticket):
            yield {"type": "queue", "position": position}
        started = True
        yield {"type": "start", "total": 1}
        async with httpx.AsyncClient() as client:
            result = await chat(client, DRAFT_SYSTEM, prompt, DRAFT_SCHEMA, model=OVERVIEW_MODEL, options=DRAFT_OPTIONS)
            title, body = draft_from_reply(result)
            if body is None:
                # The model sometimes answers with a title and an empty paragraph list (about 1 in 25-35
                # drafts in training/generation_eval, mostly personal pieces). One more sample usually
                # works; with a fixed seed the same draw would repeat, so the retry moves it on.
                options = {**DRAFT_OPTIONS, "seed": DRAFT_OPTIONS["seed"] + 1} if "seed" in DRAFT_OPTIONS else DRAFT_OPTIONS
                result = await chat(client, DRAFT_SYSTEM, prompt, DRAFT_SCHEMA, model=OVERVIEW_MODEL, options=options)
                title, body = draft_from_reply(result)
        if body is None:
            yield {"type": "error", "message": "The model didn't return a draft. Try again or reword the prompt."}
            return
        yield {"type": "draft", "title": title, "body": body}
        yield {"type": "done"}
    finally:
        await queue.leave(ticket, started)


async def model_available():
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        names = {m["name"] for m in resp.json().get("models", [])}
        return all(m in names or f"{m}:latest" in names for m in {MODEL, OVERVIEW_MODEL})
    except httpx.HTTPError:
        return False
