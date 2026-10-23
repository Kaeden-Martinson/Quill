"""Builds a small comparison set of human-written prose for the writing experiments.

    .venv\\Scripts\\python training\\human_corpus.py micusp|wac|sec|k8s|all

Everything goes to data/human_corpus/<source>/ (git-ignored, never committed or redistributed),
with one passage per .txt file and a line per passage in data/human_corpus/manifest.jsonl giving
its source URL, author or filer, year, license or terms, and why it was chosen. The set is for
evaluation only: build_dataset.py never reads it, so nothing here can leak into training.

Sources, all chosen from before late 2022 so AI-assisted text is unlikely:
  micusp  Michigan Corpus of Upper-level Student Papers (2000s; free for research and teaching,
          non-commercial). Closest to what Quill's users write.
  wac     WAC Clearinghouse open-access books published 2021 or earlier (licenses per book,
          usually CC BY-NC-ND; read and evaluated privately, not modified or republished).
  sec     The MD&A section of 10-K annual reports for fiscal 2019-2021 (U.S. public records).
          Requests are limited to under 2 per second with an identifying User-Agent, per the SEC.
  k8s     Kubernetes concept docs from the release-1.22 branch as of the end of 2021 (CC BY 4.0).
"""
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
from lxml import html

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "human_corpus"
MANIFEST = OUT / "manifest.jsonl"
AGENT = "Quill writing-eval research (personal, non-commercial project)"
client = httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": AGENT})
_last = [0.0]


def get(url, **kw):
    """Polite fetch: at most ~2 requests a second to any source."""
    wait = 0.6 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    r = client.get(url, **kw)
    r.raise_for_status()
    return r


# ---------- choosing a passage ----------

def prose(paragraph):
    """A paragraph of running prose: long enough, mostly words, not a table row or a heading."""
    words = paragraph.split()
    if len(words) < 35:
        return False
    digits = sum(ch.isdigit() for ch in paragraph)
    return digits / max(1, len(paragraph)) < 0.04 and paragraph.count("|") < 2


def passage(paragraphs, low=300, high=800, skip=0):
    """The first run of consecutive prose paragraphs adding up to low-high words."""
    best = []
    for start in range(skip, len(paragraphs)):
        run, count = [], 0
        for p in paragraphs[start:]:
            if not prose(p):
                break
            if count + len(p.split()) > high and count >= low:
                break
            run.append(p)
            count += len(p.split())
            if count >= high:
                break
        if count >= low:
            return run
        if count > sum(len(p.split()) for p in best):
            best = run
    return best if sum(len(p.split()) for p in best) >= 200 else []


def clean(text):
    return re.sub(r"[ \t]+", " ", text.replace(" ", " ")).strip()


def save(source, pid, paragraphs, meta):
    folder = OUT / source
    folder.mkdir(parents=True, exist_ok=True)
    text = "\n\n".join(clean(p) for p in paragraphs)
    (folder / f"{pid}.txt").write_text(text + "\n", encoding="utf-8")
    entry = {"source": source, "id": pid, "words": len(text.split()), **meta}
    with open(MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"  saved {source}/{pid} ({entry['words']} words)")


def reset(source):
    """Re-running a source replaces its files and manifest lines, so the set never doubles up."""
    folder = OUT / source
    for p in folder.glob("*.txt") if folder.exists() else []:
        p.unlink()
    if MANIFEST.exists():
        keep = [line for line in MANIFEST.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line)["source"] != source]
        MANIFEST.write_text("".join(line + "\n" for line in keep), encoding="utf-8")


# ---------- MICUSP ----------

MICUSP = "https://micusp.elicorpora.info"
DEPTS = ["BIO", "CEE", "CLS", "ECO", "EDU", "ENG", "HIS", "IOE", "LIN", "MEC", "NRE", "NUR", "PHI", "PHY", "POL", "PSY", "SOC"]


def micusp():
    """One paper per discipline. The site's list ignores filters, but paper IDs follow the pattern
    DEPT.G<level>.<student>.<paper> and open directly, so candidates are tried in a fixed order."""
    reset("micusp")
    for dept in DEPTS:
        candidates = [f"{dept}.G{level}.{student:02d}.1" for student in (1, 2, 3, 4, 5) for level in (0, 1, 2, 3)]
        for pid in candidates:
            try:
                page = get(f"{MICUSP}/view", params={"pid": pid}).text
            except httpx.HTTPError:
                continue
            doc = html.fromstring(page)
            body = doc.xpath('//*[@id="paperBody"]')
            if not body:
                continue
            kind = re.search(r"Paper type:\s*</td>\s*<td>([^<]+)", page)
            paras = [p.text_content() for p in body[0].xpath(".//p")] or body[0].text_content().split("\n\n")
            chosen = passage([clean(p) for p in paras if clean(p)], skip=1)
            if chosen:
                save("micusp", pid, chosen, {
                    "url": f"{MICUSP}/view?pid={pid}", "author": "anonymous University of Michigan student",
                    "year": "2000s", "type": kind.group(1).strip() if kind else "",
                    "terms": "MICUSP: free for research and teaching, non-commercial; (c) Regents of the University of Michigan",
                    "why": f"student paper ({dept}); closest match to Quill's users"})
                break


# ---------- WAC Clearinghouse ----------

WAC = "https://wacclearinghouse.org"


def wac(want=8, chapters_per_book=2):
    from pypdf import PdfReader
    reset("wac")
    listing = html.fromstring(get(f"{WAC}/books/allbooks/").text)
    links = sorted({a.get("href") for a in listing.xpath("//a[@href]")
                    if re.fullmatch(r"(https://wacclearinghouse\.org)?/books/[a-z0-9-]+/[a-z0-9-]+/?(?:[a-z0-9-]+/)?",
                                    a.get("href") or "")})
    # Spread picks across the list (which is grouped by series) instead of taking the first few.
    step = max(1, len(links) // (want * 3))
    picked, series_seen = 0, set()
    for href in links[::step]:
        if picked == want:
            break
        url = href if href.startswith("http") else WAC + href
        series = url.split("/books/")[1].split("/")[0]
        try:
            page = get(url).text
        except httpx.HTTPError:
            continue
        # The book's own notice ("Copyright © 2016 ..."), not the site footer ("Copyright on the materials ...").
        found = re.search(r"Copyright\s*(?:&copy;|©|�)?\s*((?:19|20)\d{2})", page)
        year = int(found.group(1)) if found else None
        if not year or year > 2021 or series in series_seen and len(series_seen) < want:
            continue
        lic = re.search(r"Creative Commons ([A-Za-z\-– ]+?\d\.\d[^<.]*)", page)
        pdfs = [h for h in re.findall(r'href="([^"]+/chapter\d+\.pdf)"', page)]
        pdfs = [p if p.startswith("http") else WAC + p for p in dict.fromkeys(pdfs)]
        if len(pdfs) < 2:
            continue
        title = html.fromstring(page).findtext(".//title") or url
        saved = 0
        for pdf_url in pdfs[1:1 + chapters_per_book]:  # skip chapter 1, often an editor's overview
            try:
                reader = PdfReader(io.BytesIO(get(pdf_url).content))
            except Exception:  # noqa: BLE001  a malformed PDF just skips this chapter
                continue
            text = "\n".join(page.extract_text() or "" for page in reader.pages[1:8])
            text = re.sub(r"-\n(?=[a-z])", "", text)                     # re-join hyphenated words
            lines = [ln.strip() for ln in text.split("\n")]
            lines = [ln for ln in lines if ln and not re.fullmatch(r"\d{1,3}|[A-Z][A-Za-z ,.:&'-]{0,60}\s\d{1,3}", ln)]
            paras, cur = [], []
            for ln in lines:  # pypdf gives lines; rebuild paragraphs at sentence-final line ends
                cur.append(ln)
                if re.search(r"[.!?\"”)]$", ln) and len(" ".join(cur).split()) > 60:
                    paras.append(" ".join(cur))
                    cur = []
            chosen = passage(paras)
            if chosen:
                pid = f"{url.rstrip('/').split('/')[-1]}-{pdf_url.rsplit('/', 1)[1][:-4]}"
                save("wac", pid, chosen, {"url": pdf_url, "book": clean(title), "year": year,
                                          "terms": f"Creative Commons {lic.group(1).strip()}" if lic else "see book page",
                                          "why": f"published academic prose ({series} series)"})
                saved += 1
        if saved:
            picked += 1
            series_seen.add(series)


# WAC Clearinghouse answers scripted PDF requests with 403 Forbidden, so the WAC books come from
# their LibreTexts editions instead (same text and license), at LibreTexts' requested pace of one
# request every 5 seconds (its robots.txt Crawl-delay).
LIBRETEXTS_WAC = {
    "The Centrality of Style (Duncan & Vanguri, 2013)":
        "https://human.libretexts.org/Bookshelves/Composition/Advanced_Composition/The_Centrality_of_Style_(Duncan_and_Vanguri)",
    "A Theory of Literate Action (Bazerman, 2013)":
        "https://human.libretexts.org/Bookshelves/Literature_and_Literacy/Literacy_and_Critical_Thinking/A_Theory_of_Literate_Action_-_Literate_Action_II_(Bazerman)",
    "Information Literacy: Research and Collaboration across Disciplines (D'Angelo et al., 2016)":
        "https://human.libretexts.org/Bookshelves/Research_and_Information_Literacy/Information_Literacy_-_Research_and_Collaboration_across_Disciplines_(D'Angelo)",
    "International Advances in Writing Research (Bazerman et al., 2012)":
        "https://human.libretexts.org/Bookshelves/Composition/Specialized_Composition/Book%3A_International_Advances_in_Writing_Research_-_Cultures_Places_Measures_(Bazerman_et_al.)",
    "Beyond Argument: Essaying as a Practice of (Ex)Change (Allen, 2015)":
        "https://human.libretexts.org/Bookshelves/Composition/Advanced_Composition/Beyond_Argument_-_Essaying_as_a_Practice_of_(Ex)Change_(Allen)",
    "Placing the History of College Writing (Shepley, 2016)":
        "https://human.libretexts.org/Bookshelves/Composition/Specialized_Composition/Placing_the_History_of_College_Writing_-_Stories_from_the_Incomplete_Archive_(Shepley)",
}


def slow_get(url):
    time.sleep(5)  # LibreTexts robots.txt: Crawl-delay 5
    return get(url)


def wac_libretexts(chapters_per_book=2):
    from urllib.parse import unquote
    reset("wac")
    for title, root in LIBRETEXTS_WAC.items():
        year = int(re.search(r"(\d{4})\)$", title).group(1))
        try:
            front = html.fromstring(slow_get(root).text)
        except httpx.HTTPError as exc:
            print(f"  {title}: {exc}")
            continue
        sections = [h for h in dict.fromkeys(a.get("href") for a in front.xpath("//a[@href]"))
                    if h and h.startswith(root + "/") and h.count("/") == root.count("/") + 1
                    and not re.search(r"Front_Matter|Back_Matter|zz%3A", h)]
        lic, saved = None, 0
        for section in sections:
            if saved == chapters_per_book:
                break
            try:
                page = html.fromstring(slow_get(section).text)
            except httpx.HTTPError:
                continue
            # A part page lists chapters; a chapter page has prose. Try the page, then its first child.
            candidates = [(section, page)]
            kids = [h for h in dict.fromkeys(a.get("href") for a in page.xpath("//a[@href]"))
                    if h and h.startswith(section + "/") and h.count("/") == section.count("/") + 1]
            for url, doc in candidates + [(kids[0], None)] if kids else candidates:
                if doc is None:
                    try:
                        doc = html.fromstring(slow_get(url).text)
                    except httpx.HTTPError:
                        continue
                body = doc.xpath('//*[contains(@class, "mt-content-container")]')
                paras = [clean(p.text_content()) for p in (body[0].xpath(".//p") if body else [])]
                chosen = passage([p for p in paras if p])
                lic = lic or re.search(r"(CC BY[-A-Z ]*\d\.\d(?: US)?)", doc.text_content())
                if chosen:
                    name = re.sub(r"\W+", "-", unquote(url.rstrip("/").rsplit("/", 1)[1]))[:60].strip("-").lower()
                    book = re.sub(r"\W+", "-", title.split("(")[0])[:30].strip("-").lower()
                    save("wac", f"{book}--{name}", chosen, {
                        "url": url, "book": title, "year": year, "publisher": "WAC Clearinghouse (via LibreTexts)",
                        "terms": lic.group(1) if lic else "Creative Commons (see book's Publication Information)",
                        "why": "published academic prose about writing"})
                    saved += 1
                    break
        if not saved:
            print(f"  {title}: no chapter with a long enough prose run")


# ---------- SEC EDGAR ----------

# Varied industries; CIKs from SEC's company list.
COMPANIES = {"Apple": 320193, "Microsoft": 789019, "Johnson & Johnson": 200406, "Walmart": 104169, "Ford": 37996,
             "Delta Air Lines": 27904, "Costco": 909832, "Nike": 320187, "Pfizer": 78003, "Caterpillar": 18230,
             "Starbucks": 829224, "Exxon Mobil": 34088, "Target": 27419, "Boeing": 12927, "Netflix": 1065280,
             # Spares, in case a filing above has no usable prose run.
             "Home Depot": 354950, "Coca-Cola": 21344, "Intel": 50863}
SEC_WANT = 15


def block_text(doc):
    """Text of an HTML filing with a blank line after every block element, so paragraphs survive."""
    for el in doc.iter("p", "div", "tr", "br", "li", "h1", "h2", "h3", "h4", "table"):
        el.tail = "\n\n" + (el.tail or "")
    return doc.text_content()


def sec():
    reset("sec")
    years = [2019, 2020, 2021]
    saved = 0
    for n, (name, cik) in enumerate(COMPANIES.items()):
        if saved == SEC_WANT:
            break
        want_year = years[n % 3]
        filings = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["filings"]
        rows = [dict(zip(filings["recent"], vals)) for vals in zip(*filings["recent"].values())]
        # Busy filers push older 10-Ks out of "recent" into extra pages listed under "files".
        for extra in filings.get("files", []):
            if not any(r["form"] == "10-K" and r.get("reportDate", "")[:4] in map(str, years) for r in rows):
                page = get(f"https://data.sec.gov/submissions/{extra['name']}").json()
                rows += [dict(zip(page, vals)) for vals in zip(*page.values())]
        tenk = [r for r in rows if r["form"] == "10-K" and r.get("reportDate", "")[:4] == str(want_year)]
        if not tenk:
            tenk = [r for r in rows if r["form"] == "10-K" and r.get("reportDate", "")[:4] in map(str, years)]
        if not tenk:
            print(f"  no FY2019-2021 10-K for {name}")
            continue
        f = tenk[0]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{f['accessionNumber'].replace('-', '')}/{f['primaryDocument']}"
        doc = html.fromstring(get(url).content)
        text = block_text(doc)
        # MD&A runs from "Item 7. Management's Discussion..." to "Item 7A"; the last such heading
        # is the section itself (the first is usually the table of contents).
        starts = [m.end() for m in re.finditer(r"item\s*7\.?\s*[\-–—:]?\s*management.{0,3}s\s+discussion", text, re.I)]
        if not starts:
            print(f"  no MD&A heading found for {name}")
            continue
        start = starts[-1]
        end = re.search(r"item\s*7a\.?", text[start:], re.I)
        mdna = text[start:start + end.start()] if end else text[start:start + 200000]
        paras = [clean(p) for p in re.split(r"\n\s*\n", mdna) if clean(p)]
        chosen = passage(paras)
        if not chosen:
            print(f"  {name}: MD&A found ({len(mdna.split())} words) but no run of prose paragraphs long enough")
        if chosen:
            save("sec", f"{name.lower().replace(' ', '-').replace('&', 'and')}-fy{f['reportDate'][:4]}", chosen, {
                "url": url, "author": f"{name} (10-K filer)", "year": int(f["filingDate"][:4]),
                "terms": "U.S. SEC public filing", "why": "professional business prose (MD&A narrative)"})
            saved += 1


# ---------- Kubernetes docs ----------

def k8s(want=15):
    reset("k8s")
    repo = OUT / "_k8s_repo"
    if not repo.exists():
        subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", "--branch", "release-1.22",
                        "https://github.com/kubernetes/website", str(repo)], check=True)
    commit = subprocess.run(["git", "-C", str(repo), "rev-list", "-1", "--before=2021-12-31", "origin/release-1.22"],
                            capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", "-C", str(repo), "sparse-checkout", "set", "content/en/docs/concepts"], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "--quiet", commit], check=True)
    files = sorted((repo / "content/en/docs/concepts").rglob("*.md"))
    files = [f for f in files if f.name != "_index.md"]
    step = max(1, len(files) // (want * 2))
    saved = 0
    for path in files[::step]:
        if saved == want:
            break
        md = path.read_text(encoding="utf-8")
        md = re.sub(r"\A---.*?---", "", md, flags=re.S)                    # front matter
        md = re.sub(r"```.*?```", "", md, flags=re.S)                      # code blocks
        md = re.sub(r"\{\{[<%].*?[>%]\}\}", "", md, flags=re.S)            # Hugo shortcodes
        md = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", md)                 # links -> their text
        md = re.sub(r"`([^`]*)`", r"\1", md)
        md = re.sub(r"<[^>]+>", "", md)
        paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", md)]
        paras = [p for p in paras if p and not p.startswith(("#", "-", "*", "|", ">")) and not re.match(r"\d+\.", p)]
        chosen = passage(paras, low=250)
        if chosen:
            rel = path.relative_to(repo / "content/en/docs").with_suffix("")
            save("k8s", str(rel).replace("\\", "-").replace("/", "-"), chosen, {
                "url": f"https://github.com/kubernetes/website/blob/{commit}/content/en/docs/{rel.as_posix()}.md",
                "author": "The Kubernetes Authors", "year": 2021, "terms": "CC BY 4.0",
                "why": "technical documentation (concepts)"})
            saved += 1


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    steps = {"micusp": micusp, "wac": wac_libretexts, "sec": sec, "k8s": k8s}
    for name in (steps if sys.argv[1] == "all" else [sys.argv[1]]):
        print(f"{name}:")
        try:
            steps[name]()
        except Exception as exc:  # noqa: BLE001  report and go on to the next source
            print(f"  FAILED: {type(exc).__name__}: {exc}")
