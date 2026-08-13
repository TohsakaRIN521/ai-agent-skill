#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge several search_arxiv.py --json outputs, deduplicating by arXiv id.

Usage:
  python merge_search_json.py search1.json search2.json ... [--json merged.json]

Prints a compact deduplicated list (index, id, published date, title, journal)
and optionally writes the merged entries back to JSON for later classification.
"""
import argparse
import json
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def base_id(paper_id):
    """Strip a trailing version suffix so the same paper returned by different
    queries (e.g. 2606.10418v1 vs 2606.10418v2) collapses to one entry."""
    return re.sub(r"v\d+$", "", paper_id or "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", help="JSON files from search_arxiv.py --json")
    ap.add_argument("--json", metavar="FILE", help="also save merged results to FILE as JSON")
    args = ap.parse_args(argv)

    merged, order = {}, []
    for path in args.files:
        with open(path, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
        for paper in entries:
            key = base_id(paper.get("id", ""))
            if key and key not in merged:
                merged[key] = paper
                order.append(key)

    papers = [merged[k] for k in order]
    for i, paper in enumerate(papers, 1):
        jr = paper.get("journal_ref") or ""
        authors = ", ".join(paper.get("authors", [])[:2])
        if len(paper.get("authors", [])) > 2:
            authors += " et al."
        print("[{:2}] {} | {} | {}".format(
            i, paper.get("id", ""), paper.get("published", ""), paper.get("title", "")))
        print("     journal: {} | {}".format(jr, authors))

    print("\nTOTAL UNIQUE: {}".format(len(papers)), file=sys.stderr)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(papers, fh, ensure_ascii=False, indent=2)
        print("Saved merged JSON: {}".format(args.json), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
