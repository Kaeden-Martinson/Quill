"""The sealed final test set: student paragraphs no test or training set has used, with planted errors.

    .venv\\Scripts\\python training\\sealed_test.py build     # fetch paragraphs, plant errors, seal

Paragraphs come from MICUSP papers by students other than the ones in data/human_corpus (that set
used student 01 in each discipline; this one uses students 02-05). Errors are planted by the same code
and rules as the other reliability sets (reliability.build), so scores are comparable.

Sealing: the cases' sha256 goes in training/rounds/sealed_test.json, which is committed. Scoring
needs QUILL_TESTSET=sealed and QUILL_UNSEAL=1 (reliability.py), and every scoring run is appended to
training/rounds/sealed_log.jsonl. It's meant to be scored once, after the candidate is chosen on the
other tests; nothing is tuned on it.
"""
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from lxml import html

import human_corpus as hc

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "data" / "sealed_test"
WANT = 150


def fetch():
    rng = random.Random(20261023)
    found = []
    for dept in hc.DEPTS:
        for student in (2, 3, 4, 5):
            for level in (0, 1, 2, 3):
                pid = f"{dept}.G{level}.{student:02d}.1"
                try:
                    page = hc.get(f"{hc.MICUSP}/view", params={"pid": pid}).text
                except Exception:  # noqa: BLE001  a missing ID just isn't a paper
                    continue
                body = html.fromstring(page).xpath('//*[@id="paperBody"]')
                if not body:
                    continue
                paras = [hc.clean(p.text_content()) for p in body[0].xpath(".//p")]
                paras = [p for p in paras if 50 <= len(p.split()) <= 160 and hc.prose(p)]
                rng.shuffle(paras)
                found += [{"paragraph": p, "paper": pid} for p in paras[:3]]  # at most 3 per paper
                break  # one paper per student
    rng.shuffle(found)
    return found[:WANT]


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = fetch()
    with open(OUT / "paragraphs.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    env = {**os.environ, "QUILL_TESTSET": "sealed", "PYTHONIOENCODING": "utf-8"}
    subprocess.run([sys.executable, str(HERE / "reliability.py"), "build"], check=True, env=env)
    digest = hashlib.sha256((OUT / "cases.jsonl").read_bytes()).hexdigest()
    papers = sorted({r["paper"] for r in rows})
    record = {"built": time.strftime("%Y-%m-%d %H:%M"), "cases_sha256": digest, "paragraphs": len(rows),
              "papers": papers, "source": "MICUSP (students 02-05; human_corpus used student 01)",
              "terms": "MICUSP: free for research and teaching, non-commercial; (c) Regents of the University of Michigan",
              "rule": "score once, after choosing the candidate; never tune on it"}
    (HERE / "rounds").mkdir(exist_ok=True)
    (HERE / "rounds" / "sealed_test.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(f"sealed: {len(rows)} paragraphs from {len(papers)} papers; cases sha256 {digest[:16]}...")


if __name__ == "__main__":
    {"build": build}[sys.argv[1]]()
