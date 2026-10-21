// Run with: node --test tests/frontend
const test = require("node:test");
const assert = require("node:assert/strict");
const { paragraphSpans, occurrences, locate } = require("../../frontend/text.js");

const Q = "Students uses laptops.";
const TEXT = `${Q}\n\nMy school.\n\n${Q}`;

test("paragraphs split on blank lines and ignore surrounding whitespace", () => {
  assert.deepEqual(paragraphSpans("  a\n\n \n b \n\nc").map((s) => [s.start, s.end]), [[2, 3], [8, 9], [12, 13]]);
  assert.deepEqual(paragraphSpans(""), []);
});

test("occurrences respects the range and never hangs on an empty needle", () => {
  assert.deepEqual(occurrences("abcabc", "abc"), [0, 3]);
  assert.deepEqual(occurrences("abcabc", "abc", 1), [3]);
  assert.deepEqual(occurrences("abcabc", "abc", 0, 5), [0]);
  assert.deepEqual(occurrences("abc", ""), []);
});

test("a repeated sentence is located in the paragraph its suggestion came from", () => {
  assert.equal(locate({ original: Q, paragraph: 0 }, TEXT), 0);
  assert.equal(locate({ original: Q, paragraph: 2 }, TEXT), TEXT.lastIndexOf(Q));
});

test("a suggestion whose text was edited is stale, not moved to another paragraph", () => {
  const edited = `${Q}\n\nMy school.\n\nStudents use laptops.`;
  assert.equal(locate({ original: Q, paragraph: 2 }, edited), -1);
});

test("if the paragraph is gone, fall back only to a unique match", () => {
  assert.equal(locate({ original: "My school.", paragraph: 9 }, TEXT), TEXT.indexOf("My school."));
  assert.equal(locate({ original: Q, paragraph: 9 }, TEXT), -1);
});

test("extra blank lines between paragraphs don't shift the anchor", () => {
  const spaced = `${Q}\n\n\n   \nMy school.\n\n${Q}`;
  assert.equal(locate({ original: Q, paragraph: 2 }, spaced), spaced.lastIndexOf(Q));
});

test("frontend and server agree on paragraph count", () => {
  // Same cases the server's split_paragraphs handles: CRLF, tabs, and trailing blank lines.
  assert.equal(paragraphSpans("one\r\n\r\ntwo\n\t\nthree\n\n\n").length, 3);
});
