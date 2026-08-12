#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Search arXiv (past N years) for papers related to given keywords.

Prints a relevance-ranked list (default 40) with arXiv ID, title, authors,
published date, journal reference (if present) and abstract snippet.
Optionally saves results as JSON for later steps.
"""
import argparse
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


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
        abstract = " ".join((entry.findtext("atom:summary", default="", namespaces=NS) or "").split())
        entries.append(
            {
                "id": paper_id,
                "title": title,
                "authors": authors,
                "published": published,
                "journal_ref": journal_ref or None,
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

    for i, paper in enumerate(entries, 1):
        journal = " | journal: {}".format(paper["journal_ref"]) if paper["journal_ref"] else ""
        authors = ", ".join(paper["authors"][:3]) + (" et al." if len(paper["authors"]) > 3 else "")
        print("[{:2}] {} - {}{}".format(i, paper["id"], paper["title"], journal))
        print("     {} ({}) | {} ...".format(authors, paper["published"], paper["abstract"][:160]))
        print()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=2)
        print("Saved JSON: {}".format(args.json), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
