// Run with: node --test tests/frontend
const test = require("node:test");
const assert = require("node:assert/strict");
const { aiParagraphs, syllables, sentenceSpans, readThrough } = require("../../frontend/text.js");

test("a paragraph stays AI-written until most of its words are the writer's", () => {
  const ai = "The bus is slow and it is always late in the morning.\n\nBikes are cheap.";
  const text = "The bus is slow and it is always late.\n\nHonestly the bus drives me up a wall every day.";
  assert.deepEqual(aiParagraphs(text, ai).map((p) => p.ai), [true, false]);
  assert.deepEqual(aiParagraphs(text, null).map((p) => p.ai), [false, false]);
});

test("the AI check remembers paragraphs it has already measured", () => {
  const cache = new Map();
  aiParagraphs("Bikes are cheap.", "Bikes are cheap.", cache);
  assert.equal(cache.get("Bikes are cheap."), true);
});

test("syllable counts are close enough for a reading level", () => {
  assert.equal(syllables("cat"), 1);
  assert.equal(syllables("table"), 2);
  assert.equal(syllables("education"), 4);
  assert.equal(syllables("made"), 1);
});

test("sentences never cross a paragraph break and keep their closing quotes", () => {
  const text = 'He said "stop." Then left\n\nNew one! Another?';
  const spans = sentenceSpans(text).map((s) => text.slice(s.start, s.end));
  assert.deepEqual(spans, ['He said "stop."', "Then left", "New one!", "Another?"]);
});

test("the report finds passive voice, adverbs, repeated words and long sentences", () => {
  const long = `${"word ".repeat(32).trim()}.`;
  const text = `The window was broken by someone. I was excited. She quickly ran. Really, the garden garden garden grew.\n\n${long}`;
  const r = readThrough(text);
  assert.deepEqual(r.passive.map((p) => p.text), ["was broken"]);
  assert.deepEqual(r.adverbs.map((a) => a.text), ["quickly", "Really"]);
  assert.deepEqual(r.repeated.map((c) => [c.word, c.count]), [["word", 32], ["garden", 3]]);
  assert.equal(r.long.length, 1);
  assert.ok(r.grade > 0 && r.avgWords > 0);
  assert.equal(text.slice(r.passive[0].start, r.passive[0].end), "was broken");
});

test("an empty draft gives an empty report", () => {
  const r = readThrough("");
  assert.equal(r.words, 0);
  assert.equal(r.grade, 0);
  assert.deepEqual(r.sentences, []);
});
