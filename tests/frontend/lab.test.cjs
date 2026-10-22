// Run with: node --test tests/frontend
const test = require("node:test");
const assert = require("node:assert/strict");
const { applyCutoffs } = require("../../frontend/text.js");

// The model's real chances for its first word when asked to "Say hello".
const HELLO = [["Hello", 0.884], ["Hi", 0.094], ["Hey", 0.013], ['"', 0.0024], ["hi", 0.0007]];
const kept = (rows) => rows.filter((r) => r.kept).map((r) => r.token);

test("temperature 0 keeps only the likeliest word", () => {
  const rows = applyCutoffs(HELLO, { temperature: 0, top_p: 0.9, top_k: 40, min_p: 0 });
  assert.deepEqual(kept(rows), ["Hello"]);
  assert.equal(rows[0].chance, 1);
  assert.equal(rows[1].cutBy, "temperature");
});

test("top_p keeps words until their chances add up to the cutoff", () => {
  assert.deepEqual(kept(applyCutoffs(HELLO, { temperature: 1, top_p: 0.9, top_k: 0, min_p: 0 })), ["Hello", "Hi"]);
  assert.deepEqual(kept(applyCutoffs(HELLO, { temperature: 1, top_p: 0.5, top_k: 0, min_p: 0 })), ["Hello"]);
  assert.equal(applyCutoffs(HELLO, { temperature: 1, top_p: 0.5, top_k: 0, min_p: 0 })[1].cutBy, "top_p");
});

test("top_k keeps a fixed number, min_p a share of the top word's chance", () => {
  assert.deepEqual(kept(applyCutoffs(HELLO, { temperature: 1, top_p: 1, top_k: 3, min_p: 0 })), ["Hello", "Hi", "Hey"]);
  assert.deepEqual(kept(applyCutoffs(HELLO, { temperature: 1, top_p: 1, top_k: 0, min_p: 0.05 })), ["Hello", "Hi"]);
  assert.deepEqual(kept(applyCutoffs(HELLO, { temperature: 1, top_p: 1, top_k: 0, min_p: 0.01 })), ["Hello", "Hi", "Hey"]);
});

test("higher temperature spreads the chances out; the kept chances add to 100%", () => {
  const cool = applyCutoffs(HELLO, { temperature: 0.5, top_p: 1, top_k: 0, min_p: 0 });
  const warm = applyCutoffs(HELLO, { temperature: 1.5, top_p: 1, top_k: 0, min_p: 0 });
  assert.ok(warm[1].chance > cool[1].chance);
  const sum = warm.filter((r) => r.kept).reduce((a, r) => a + r.chance, 0);
  assert.ok(Math.abs(sum - 1) < 1e-9);
});
