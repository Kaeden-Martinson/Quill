// Pure text helpers for locating suggestions in a draft. No DOM access, so they run in the
// browser (as globals, loaded before app.js) and in Node for tests (as a CommonJS module).
(function (exports) {
  // Paragraph boundaries, split the same way the server splits them (blank lines, trimmed).
  function paragraphSpans(text) {
    const spans = [];
    const re = /\n\s*\n/g;
    let start = 0;
    for (let m = re.exec(text); ; m = re.exec(text)) {
      const end = m ? m.index : text.length;
      const raw = text.slice(start, end);
      const lead = raw.length - raw.trimStart().length;
      const trimmed = raw.trim();
      if (trimmed) spans.push({ start: start + lead, end: start + lead + trimmed.length });
      if (!m) break;
      start = m.index + m[0].length;
    }
    return spans;
  }

  // Start offsets of `needle` that lie entirely within [from, to).
  function occurrences(text, needle, from = 0, to = text.length) {
    if (!needle) return []; // indexOf("") matches everywhere and would never advance past the end
    const found = [];
    for (let at = text.indexOf(needle, from); at !== -1 && at + needle.length <= to; at = text.indexOf(needle, at + 1)) {
      found.push(at);
    }
    return found;
  }

  // Where a suggestion's quote sits now. If its paragraph still exists, only that paragraph is
  // searched: once the writer has changed the quoted text there, the suggestion is stale, even if
  // the same words appear in another paragraph. Only when the paragraph is gone (paragraphs were
  // removed) does it fall back to a quote that appears exactly once. Returns -1 when unsure, so
  // an edit is never applied to the wrong copy of a repeated phrase.
  function locate(s, text) {
    if (s.paragraph != null) {
      const para = paragraphSpans(text)[s.paragraph];
      if (para) return occurrences(text, s.original, para.start, para.end)[0] ?? -1;
    }
    const all = occurrences(text, s.original);
    return all.length === 1 ? all[0] : -1;
  }

  // Word-level diff of a suggestion, for drawing it as an editor's markup: only the words that
  // change get struck through and rewritten, not the whole quoted sentence. Spaces are their own
  // tokens so the "keep" and "del" segments concatenate back to `original` exactly.
  // Returns [{type: "keep"|"change", del: string, ins: string}].
  function diffWords(original, revised) {
    const a = original.match(/\s+|[^\s]+/g) || [];
    const b = revised.match(/\s+|[^\s]+/g) || [];
    // Longest common subsequence table, built from the end.
    const lcs = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
    for (let i = a.length - 1; i >= 0; i--) {
      for (let j = b.length - 1; j >= 0; j--) {
        lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
      }
    }
    const out = [];
    const push = (type, del, ins) => {
      const last = out[out.length - 1];
      if (last && last.type === type) { last.del += del; last.ins += ins; } else out.push({ type, del, ins });
    };
    let i = 0, j = 0;
    while (i < a.length || j < b.length) {
      if (i < a.length && j < b.length && a[i] === b[j]) { push("keep", a[i], ""); i++; j++; }
      else if (j < b.length && (i === a.length || lcs[i][j + 1] >= lcs[i + 1][j])) { push("change", "", b[j]); j++; }
      else { push("change", a[i], ""); i++; }
    }
    // A change that only swaps spaces is noise in markup; fold whitespace-only changes into "keep".
    const segs = out.map((seg) => (seg.type === "change" && !seg.del.trim() && !seg.ins.trim()
      ? { type: "keep", del: seg.del, ins: "" } : seg));
    // Two changes separated by at most one kept word read better as one stroke, the way an editor
    // would mark "me and my brother" -> "my brother and I" rather than as two crossed-out bits.
    const merged = [];
    for (const seg of segs) {
      const prev = merged[merged.length - 1], before = merged[merged.length - 2];
      if (seg.type === "change" && prev && prev.type === "keep" && before && before.type === "change"
          && prev.del.trim().split(/\s+/).filter(Boolean).length <= 1) {
        before.del += prev.del + seg.del;
        before.ins += prev.del + seg.ins;
        merged.pop();
      } else if (seg.type === "change" && prev && prev.type === "change") {
        prev.del += seg.del; prev.ins += seg.ins;
      } else {
        merged.push({ ...seg });
      }
    }
    return merged;
  }

  exports.paragraphSpans = paragraphSpans;
  exports.occurrences = occurrences;
  exports.locate = locate;
  exports.diffWords = diffWords;
})(typeof module !== "undefined" ? module.exports : window);
