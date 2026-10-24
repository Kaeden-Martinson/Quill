// Run with: node --test tests/frontend
const test = require("node:test");
const assert = require("node:assert/strict");
const { looksPersonal } = require("../../frontend/text.js");

test("personal and application pieces are recognised, from the goal or the instructions", () => {
  assert.ok(looksPersonal("college application personal essay", ""));
  assert.ok(looksPersonal("scholarship essay", "Why I want to study nursing."));
  assert.ok(looksPersonal("", "Write a blog post about my month without buying anything."));
  assert.ok(looksPersonal("job application essay", ""));
  assert.ok(looksPersonal("", "A reflection on my first year of high school"));
});

test("analytical and informational pieces are not", () => {
  assert.ok(!looksPersonal("English class literary analysis", "Analyze the conch in Lord of the Flies."));
  assert.ok(!looksPersonal("explanation for 8th graders", "Explain how vaccines work."));
  assert.ok(!looksPersonal("persuasive essay", "Argue for a later school start."));
  assert.ok(!looksPersonal("", ""));
});
