#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Search arXiv (past N years) for papers related to given keywords.

Prints a relevance-ranked list (default 40) with arXiv ID, title, authors,
published date, journal reference (if present), the paper's native DOI field
(if the author filled it in) and abstract snippet.
Optionally saves results as JSON for later steps.

The native ``arxiv:doi`` field is the most reliable first source for the
official DOI: it is filled in by the authors once the paper is published.
It is NOT the same as ``journal_ref``, which is only a free-text string like
"Phys. Rev. A 110, 023601 (2024)" and contains no DOI.
"""
import argparse
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API = "https://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

# Force UTF-8 on standard streams. Windows consoles default to GBK/CP936, and
# printing accented author names or math symbols from abstracts then raises
# UnicodeEncodeError, aborting the run before results are saved.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def build_url(query: str, limit: int, years: int) -> str:
    end = dt.date.today()
    start = end - dt.timedelta(days=365 * years)
    date_range = "submittedDate:[{:%Y%m%d} TO {:%Y%m%d}]".format(start, end)
    params = urllib.parse.urlencode(
        {
            "search_query": "({}) AND {}".format(query, date_range),
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    return "{}?{}".format(API, params)


def fetch(url: str, retries: int = 3) -> bytes:
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "arxiv-paper-completion/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as exc:  # network hiccups: retry with backoff
            last_err = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("arXiv API request failed: {}".format(last_err))


def parse_entries(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    entries = []
    for entry in root.findall("atom:entry", NS):
        paper_id = (entry.findtext("atom:id", default="", namespaces=NS) or "").rsplit("/abs/", 1)[-1]
        title = " ".join((entry.findtext("atom:title", default="", namespaces=NS) or "").split())
        published = (entry.findtext("atom:published", default="", namespaces=NS) or "")[:10]
        authors = [
            a.findtext("atom:name", default="", namespaces=NS) or ""
            for a in entry.findall("atom:author", NS)
        ]
        journal_ref = entry.findtext("arxiv:journal_ref", default="", namespaces=NS)
        # arxiv:doi is the native DOI field filled in by the authors once the
        # paper is formally published; it is the most trustworthy DOI source.
        doi = entry.findtext("arxiv:doi", default="", namespaces=NS)
        abstract = " ".join((entry.findtext("atom:summary", default="", namespaces=NS) or "").split())
        entries.append(
            {
                "id": paper_id,
                "title": title,
                "authors": authors,
                "published": published,
                "journal_ref": journal_ref or None,
                "doi": doi or None,
                "abstract": abstract,
            }
        )
    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="arXiv search query, e.g. 'floquet theory'")
    parser.add_argument("--limit", type=int, default=40, help="number of results (default 40)")
    parser.add_argument("--years", type=int, default=1, help="look back N years (default 1)")
    parser.add_argument("--json", metavar="FILE", help="also save results to FILE as JSON")
    args = parser.parse_args(argv)

    url = build_url(args.query, args.limit, args.years)
    entries = parse_entries(fetch(url))
    if not entries:
        print("No results. Try a broader query or increase --years.", file=sys.stderr)
        return 1

    # Save results to disk *before* printing, so a later failure (e.g. a console
    # encoding issue) never loses the search results.
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=2)

    for i, paper in enumerate(entries, 1):
        journal = " | journal: {}".format(paper["journal_ref"]) if paper["journal_ref"] else ""
        doi_info = " | DOI: {}".format(paper["doi"]) if paper.get("doi") else ""
        authors = ", ".join(paper["authors"][:3]) + (" et al." if len(paper["authors"]) > 3 else "")
        print("[{:2}] {} - {}{}{}".format(i, paper["id"], paper["title"], journal, doi_info))
        print("     {} ({}) | {} ...".format(authors, paper["published"], paper["abstract"][:160]))
        print()

    if args.json:
        print("Saved JSON: {}".format(args.json), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
