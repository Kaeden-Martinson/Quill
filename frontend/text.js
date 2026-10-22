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

  // ---------- AI-written paragraphs ----------

  // The same rule as backend/authorship.py: a paragraph counts as AI-written while at least half of
  // its words are still, in order, in some paragraph of Quill's AI draft.
  const AI_SHARE = 0.5;
  const wordsOf = (text) => text.toLowerCase().split(/\s+/).filter(Boolean);

  function keptShare(words, aiWords) {
    if (!words.length) return 0;
    let prev = new Array(aiWords.length + 1).fill(0);
    for (let i = 1; i <= words.length; i++) {
      const row = new Array(aiWords.length + 1).fill(0);
      for (let j = 1; j <= aiWords.length; j++) {
        row[j] = words[i - 1] === aiWords[j - 1] ? prev[j - 1] + 1 : Math.max(prev[j], row[j - 1]);
      }
      prev = row;
    }
    return prev[aiWords.length] / words.length;
  }

  // One {start, end, ai} per paragraph of text. `cache` (a Map) skips paragraphs already measured,
  // since this runs on every keystroke.
  function aiParagraphs(text, aiText, cache = new Map()) {
    const ai = aiText ? paragraphSpans(aiText).map((p) => wordsOf(aiText.slice(p.start, p.end))) : [];
    return paragraphSpans(text).map((span) => {
      const para = text.slice(span.start, span.end);
      if (!cache.has(para)) cache.set(para, ai.some((a) => keptShare(wordsOf(para), a) >= AI_SHARE));
      return { ...span, ai: cache.get(para) };
    });
  }

  // ---------- read-through report ----------

  const STOPWORDS = new Set(("about above after again against also because been before being below between both "
    + "could does doing down during each even every from further have having here herself himself however into "
    + "itself just like make made more most much myself never only other ought ourselves over really same should "
    + "some such than that their theirs them themselves then there these they thing things this those through "
    + "under until very want were what when where which while will with would your yours yourself yourselves "
    + "didn't don't it's i'm that's there's they're we're you're can't won't wasn't isn't").split(" "));
  const NOT_ADVERBS = new Set(("only family early reply supply apply rely holy ugly friendly lonely lovely silly daily "
    + "weekly monthly yearly july italy belly jelly bully fly ally rally emily lily molly holly kelly billy butterfly "
    + "assembly anomaly melancholy monopoly curly chilly costly elderly likely unlikely lively orderly timely deadly "
    + "jolly comply imply multiply sly reply") .split(" "));
  // "was excited" describes a feeling more often than it hides who did something.
  const NOT_PASSIVE = new Set(("excited interested tired bored scared worried pleased embarrassed annoyed confused "
    + "amazed disappointed involved related located supposed used married finished done gone").split(" "));
  const IRREGULAR = ("made given taken seen written known built found told held kept left lost paid said sent shown "
    + "sold taught thought brought bought caught chosen driven eaten forgotten hidden put set cut read won begun "
    + "broken spoken stolen torn worn thrown drawn grown").split(" ");
  const PASSIVE_RE = new RegExp(`\\b(?:am|is|are|was|were|be|been|being)\\s+(?:\\w+ly\\s+)?(\\w+ed|${IRREGULAR.join("|")})\\b`, "gi");

  function syllables(word) {
    const w = word.toLowerCase().replace(/[^a-z]/g, "");
    if (w.length <= 3) return 1;
    const groups = w.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, "").replace(/^y/, "").match(/[aeiouy]{1,2}/g);
    return Math.max(1, groups ? groups.length : 1);
  }

  // Sentences as offsets into text, never crossing a paragraph break.
  function sentenceSpans(text) {
    const out = [];
    for (const p of paragraphSpans(text)) {
      const re = /[^.!?]+(?:[.!?]+["'”’)\]]*|$)/g;
      const para = text.slice(p.start, p.end);
      for (let m = re.exec(para); m; m = re.exec(para)) {
        if (!m[0]) { re.lastIndex++; continue; }
        const lead = m[0].length - m[0].trimStart().length;
        const s = m[0].trim();
        if (!s) continue;
        const start = p.start + m.index + lead;
        out.push({ start, end: start + s.length, words: (s.match(/[A-Za-z0-9’']+/g) || []).length });
      }
    }
    return out.filter((s) => s.words > 0);
  }

  // A writer-facing read-through: rhythm, reading level, and patterns worth a second look. Every
  // finding carries offsets into text so the page can point at it.
  function readThrough(text) {
    const sentences = sentenceSpans(text);
    const words = [...text.matchAll(/[A-Za-z][A-Za-z’']*/g)];
    const totalWords = words.length;
    const syl = words.reduce((n, m) => n + syllables(m[0]), 0);
    const grade = totalWords && sentences.length
      ? Math.max(0, 0.39 * (totalWords / sentences.length) + 11.8 * (syl / totalWords) - 15.59) : 0;

    const counts = new Map();
    for (const m of words) {
      const w = m[0].toLowerCase().replace(/[’']s$/, "");
      if (w.length < 4 || STOPWORDS.has(w)) continue;
      const c = counts.get(w) || { word: w, count: 0, start: m.index, end: m.index + m[0].length };
      c.count++;
      counts.set(w, c);
    }
    const repeated = [...counts.values()].filter((c) => c.count >= 3)
      .sort((a, b) => b.count - a.count || a.start - b.start).slice(0, 8);

    const passive = [...text.matchAll(PASSIVE_RE)]
      .filter((m) => !NOT_PASSIVE.has(m[1].toLowerCase()))
      .map((m) => ({ text: m[0], start: m.index, end: m.index + m[0].length }));
    const adverbs = words
      .filter((m) => /ly$/i.test(m[0]) && m[0].length > 4 && !NOT_ADVERBS.has(m[0].toLowerCase()))
      .map((m) => ({ text: m[0], start: m.index, end: m.index + m[0].length }));

    return {
      words: totalWords,
      sentences,
      avgWords: sentences.length ? totalWords / sentences.length : 0,
      grade: Math.round(grade * 10) / 10,
      long: sentences.filter((s) => s.words > 30),
      repeated,
      passive,
      adverbs,
    };
  }

  exports.paragraphSpans = paragraphSpans;
  exports.occurrences = occurrences;
  exports.locate = locate;
  exports.diffWords = diffWords;
  exports.aiParagraphs = aiParagraphs;
  exports.syllables = syllables;
  exports.sentenceSpans = sentenceSpans;
  exports.readThrough = readThrough;
})(typeof module !== "undefined" ? module.exports : window);
