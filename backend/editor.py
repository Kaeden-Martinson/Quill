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
from config import MAX_CONCURRENT_REVIEWS, MODEL, OLLAMA_URL, OVERVIEW_MODEL

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


async def chat(client, system, prompt, schema, model=MODEL):
    num_ctx = context_size(system, prompt) or CONTEXT_STEPS[-1]
    resp = await client.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0.3, "num_ctx": num_ctx},
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
        if s.get("original") and s["original"] in paragraph and s.get("revised") != s["original"]
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
            result = await chat(client, OVERVIEW_SYSTEM, prompt, OVERVIEW_SCHEMA, model=OVERVIEW_MODEL)
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

DRAFT_SYSTEM = """You write a first draft of an essay from the writer's instructions, in the voice described.
Follow the voice closely: sentence length, contractions, first person, formality.
Stay on the writer's topic and points. Never invent statistics, quotes, studies, or personal
events that the writer didn't mention; where the essay needs a specific detail only the writer
knows, write a short bracketed placeholder like [your example here] instead.
Write plain paragraphs, no headings or lists. "title" is a short working title."""

DRAFT_LENGTHS = {"short": "about 250 words (3 paragraphs)", "medium": "about 500 words (5 paragraphs)",
                 "long": "about 900 words (7 paragraphs)"}


def draft_prompt(instructions, voice, sample=None, goal="", audience="", tone="", length="medium"):
    parts = [f"Writer's voice:\n{voice}"]
    if sample:
        parts.append(f"A sample of how this writer sounds (match the style, not the content):\n\"\"\"\n{sample}\n\"\"\"")
    for label, value in (("Essay goal", goal), ("Audience", audience), ("Tone", tone)):
        if value:
            parts.append(f"{label}: {value}")
    parts.append(f"Length: {DRAFT_LENGTHS.get(length, DRAFT_LENGTHS['medium'])}")
    parts.append(f"Instructions:\n\"\"\"\n{instructions}\n\"\"\"")
    return "\n\n".join(parts)


async def draft_stream(prompt):
    """Yields events: queue, start, draft (title and body), done. Uses the general model."""
    ticket, started = queue.join(), False
    try:
        async for position in take_turn(ticket):
            yield {"type": "queue", "position": position}
        started = True
        yield {"type": "start", "total": 1}
        async with httpx.AsyncClient() as client:
            result = await chat(client, DRAFT_SYSTEM, prompt, DRAFT_SCHEMA, model=OVERVIEW_MODEL)
        paragraphs = [" ".join(p.split()) for p in (result or {}).get("paragraphs", []) if p.strip()]
        if not paragraphs:
            yield {"type": "error", "message": "The model didn't return a draft. Try again or reword the prompt."}
            return
        title = " ".join(((result or {}).get("title") or "").split())[:200] or "Untitled draft"
        yield {"type": "draft", "title": title, "body": "\n\n".join(paragraphs)}
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
