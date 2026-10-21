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

  exports.paragraphSpans = paragraphSpans;
  exports.occurrences = occurrences;
  exports.locate = locate;
})(typeof module !== "undefined" ? module.exports : window);
