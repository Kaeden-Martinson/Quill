"""Professional prose for round 8's training data: paragraphs written by people, licensed for reuse.

    .venv\\Scripts\\python training\\pro_prose.py sec|python|all

Writes data/pro_prose/paragraphs.jsonl (git-ignored) with one line per paragraph: text, source
document, URL, year, license. build_dataset.py turns these into no-edit and light-edit examples.

Kept apart from the evaluation sets on purpose:
  * SEC: different companies and earlier years (fiscal 2016-2018) than data/human_corpus (FY2019-21).
    sec.gov: "public information and may be copied or further distributed" without permission;
    the SEC is credited as the source.
  * Python docs (tutorial and HOWTOs, CPython v3.10.0, Oct 2021): PSF License Version 2, which allows
    derivative works with the license notice kept. A different technical source from the Kubernetes
    pages in data/human_corpus, so those stay an unseen source.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from lxml import html

import human_corpus as hc

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pro_prose"
PARAS = OUT / "paragraphs.jsonl"

# None of these is in data/human_corpus (which used Apple, Microsoft, J&J, Walmart, Delta, Costco,
# Nike, Pfizer, Caterpillar, Starbucks, Target, Boeing, Netflix, Home Depot, Coca-Cola, Ford, Exxon).
COMPANIES = {"IBM": 51143, "PepsiCo": 77476, "Procter & Gamble": 80424, "3M": 66740, "UPS": 1090727,
             "FedEx": 1048911, "Honeywell": 773840, "McDonald's": 63908, "Kroger": 56873, "Lowe's": 60667,
             "Verizon": 732712, "Cisco": 858877, "Merck": 310158, "General Mills": 40704, "Deere": 315189,
             "Southwest Airlines": 92380, "Marriott": 1048286, "Oracle": 1341439}


def prose_paragraphs(paras, low=40, high=180):
    return [p for p in paras if low <= len(p.split()) <= high and hc.prose(p)]


def write(rows, source):
    keep = []
    if PARAS.exists():
        keep = [l for l in PARAS.read_text(encoding="utf-8").splitlines() if l.strip() and json.loads(l)["source"] != source]
    OUT.mkdir(parents=True, exist_ok=True)
    with open(PARAS, "w", encoding="utf-8") as f:
        f.writelines(line + "\n" for line in keep)
        f.writelines(json.dumps({"source": source, **r}, ensure_ascii=False) + "\n" for r in rows)
    print(f"  {source}: {len(rows)} paragraphs")


def sec(per_filing=30):
    rows = []
    for name, cik in COMPANIES.items():
        filings = hc.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["filings"]
        found = [dict(zip(filings["recent"], v)) for v in zip(*filings["recent"].values())]
        for extra in filings.get("files", []):
            page = hc.get(f"https://data.sec.gov/submissions/{extra['name']}").json()
            found += [dict(zip(page, v)) for v in zip(*page.values())]
        tenk = [r for r in found if r["form"] == "10-K" and r.get("reportDate", "")[:4] in ("2016", "2017", "2018")]
        if not tenk:
            print(f"  {name}: no FY2016-2018 10-K")
            continue
        f = tenk[0]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{f['accessionNumber'].replace('-', '')}/{f['primaryDocument']}"
        text = hc.block_text(html.fromstring(hc.get(url).content))
        starts = [m.end() for m in re.finditer(r"item\s*7\.?\s*[\-–—:]?\s*management.{0,3}s\s+discussion", text, re.I)]
        if not starts:
            print(f"  {name}: MD&A is in an exhibit, skipped")
            continue
        end = re.search(r"item\s*7a\.?", text[starts[-1]:], re.I)
        mdna = text[starts[-1]:starts[-1] + end.start()] if end else text[starts[-1]:starts[-1] + 200000]
        paras = prose_paragraphs([hc.clean(p) for p in re.split(r"\n\s*\n", mdna) if hc.clean(p)])
        for i, p in enumerate(paras[:per_filing]):
            rows.append({"text": p, "doc": f"sec-{name}-fy{f['reportDate'][:4]}", "id": f"sec-{cik}-{i:02d}",
                         "genre": "annual report (MD&A)", "url": url, "year": int(f["filingDate"][:4]),
                         "license": "SEC public information; source: U.S. Securities and Exchange Commission"})
        print(f"  {name}: {min(len(paras), per_filing)} paragraphs")
    write(rows, "sec")


def rst_paragraphs(text):
    """Prose paragraphs of a reStructuredText file: no directives, code, tables, headings or lists."""
    out = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.split("\n")
        if not lines or lines[0].startswith((" ", "\t", "..", "*", "-", "#", "=", "|", "+", ">>>")) or re.match(r"\d+\.\s", lines[0]):
            continue  # indented (code or quoted), directives, lists, headings, tables, doctest
        if len(lines) > 1 and re.fullmatch(r"[=\-~^*#\"']{3,}", lines[1].strip()):
            continue  # a heading with its underline
        p = " ".join(l.strip() for l in lines)
        p = re.sub(r":[a-z:]+:`~?([^`<]+?)(?:\s*<[^>]+>)?`", r"\1", p)   # :func:`print` -> print
        p = re.sub(r"`([^`<]+?)\s*<[^>]+>`_+", r"\1", p)               # `text <url>`_ -> text
        p = re.sub(r"``([^`]+)``", r"\1", p)
        p = re.sub(r"\*\*?([^*]+)\*\*?", r"\1", p).rstrip(":").strip()
        if p.endswith("::"):
            p = p[:-1]
        out.append(p)
    return out


def python_docs():
    repo = OUT / "_cpython"
    if not repo.exists():
        subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", "--depth", "1",
                        "--branch", "v3.10.0", "https://github.com/python/cpython", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "sparse-checkout", "set", "Doc/tutorial", "Doc/howto"], check=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "--quiet", "v3.10.0"], check=True)
    rows = []
    for path in sorted((repo / "Doc").glob("*/*.rst")):
        paras = prose_paragraphs(rst_paragraphs(path.read_text(encoding="utf-8")))
        rel = path.relative_to(repo).as_posix()
        for i, p in enumerate(paras):
            rows.append({"text": p, "doc": f"python-{path.stem}", "id": f"py-{path.parent.name}-{path.stem}-{i:02d}",
                         "genre": "technical documentation", "year": 2021,
                         "url": f"https://github.com/python/cpython/blob/v3.10.0/{rel}",
                         "license": "PSF License Version 2 (Python Software Foundation)"})
    write(rows, "python")


if __name__ == "__main__":
    steps = {"sec": sec, "python": python_docs}
    for name in (steps if sys.argv[1] == "all" else [sys.argv[1]]):
        print(f"{name}:")
        steps[name]()
