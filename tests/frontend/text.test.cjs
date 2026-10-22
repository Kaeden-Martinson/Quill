// Run with: node --test tests/frontend
const test = require("node:test");
const assert = require("node:assert/strict");
const { paragraphSpans, occurrences, locate, diffWords } = require("../../frontend/text.js");

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

const changes = (o, r) => diffWords(o, r).filter((s) => s.type === "change").map((s) => [s.del.trim(), s.ins.trim()]);

test("markup diff marks only the words that change", () => {
  const o = "By junior year I was the one who's job it was.";
  const r = "By junior year, I was the one whose job it was.";
  assert.deepEqual(changes(o, r), [["year", "year,"], ["who's", "whose"]]);
});

test("markup diff keeps the original text exactly, so it can be drawn over the textarea", () => {
  const cases = [
    ["Their was crumbs everywhere and I couldn't.", "There were crumbs everywhere and I couldn't."],
    ["me and my brother started", "my brother and I started"],
    ["I went store.", "I went to the store."],
    ["It is very really good.", "It is very good."],
  ];
  for (const [o, r] of cases) {
    assert.equal(diffWords(o, r).map((s) => s.del).join(""), o);
    // and the inserted words plus kept words rebuild the revision
    assert.equal(diffWords(o, r).map((s) => (s.type === "keep" ? s.del : s.ins)).join("").replace(/\s+/g, " "), r.replace(/\s+/g, " "));
  }
});

test("nearby changes are drawn as one stroke, the way an editor would", () => {
  assert.deepEqual(changes("Last summer me and my brother started", "Last summer my brother and I started"),
    [["me and my brother", "my brother and I"]]);
  assert.deepEqual(changes("Their was crumbs", "There were crumbs"), [["Their was", "There were"]]);
  // far-apart changes stay separate
  assert.deepEqual(changes("By junior year I was the one who's job", "By junior year, I was the one whose job"),
    [["year", "year,"], ["who's", "whose"]]);
});

test("pure insertions and deletions come out as one-sided changes", () => {
  assert.deepEqual(changes("I went store.", "I went to the store."), [["", "to the"]]);
  assert.deepEqual(changes("It is very really good.", "It is very good."), [["really", ""]]);
});
