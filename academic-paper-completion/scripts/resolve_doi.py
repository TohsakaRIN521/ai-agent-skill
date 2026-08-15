#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve the official published DOI for arXiv papers.

Priority (most reliable first):

  1. arxiv-native  : the paper's native ``arxiv:doi`` field (filled in by the
                     authors once published; the most trustworthy source).
  2. journal-ref   : (journal name + volume + page + year + authors) from
                     ``journal_ref`` queried against Crossref.
  3. title-fallback: title + first author + year queried against Crossref
                     (last resort, least reliable).
  4. none          : preprint only, no official DOI; cite the arXiv ID.

Every candidate DOI is cross-checked against the arXiv record before it is
accepted: the Crossref item's FIRST-AUTHOR SURNAME and YEAR must roughly match
the arXiv record (volume/page are additionally checked for the journal_ref
tuple path). A DOI that fails the check is never trusted blindly.

Usage:
  python resolve_doi.py 2401.08762                 # single ID (metadata auto-fetched from arXiv)
  python resolve_doi.py 2401.08762 2401.00001      # several IDs
  python resolve_doi.py --json search.json --out resolved.json   # batch from search_arxiv.py JSON
"""
import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
SELECT = "DOI,title,author,volume,page,container-title,issued,published-print,published-online"
UA = "academic-paper-completion/1.0"

# Force UTF-8 on standard streams (Windows consoles default to GBK/CP936).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

JREF_RE = re.compile(
    r"^(?P<journal>.*?)\s+(?P<volume>\d+)\s*,\s*(?P<page>\S+?)\s*\((?P<year>\d{4})\)\s*$"
)


def fetch(url: str, retries: int = 3) -> bytes:
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as exc:
            last_err = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("HTTP request failed: {}".format(last_err))


def fetch_json(url: str, retries: int = 3):
    try:
        return json.loads(fetch(url, retries))
    except Exception:
        return None


def fetch_arxiv_meta(arxiv_id: str):
    """Fetch metadata for a single arXiv ID; returns a record dict or None."""
    url = "{}?id_list={}".format(ARXIV_API, urllib.parse.quote(arxiv_id))
    try:
        data = fetch(url)
    except Exception:
        return None
    root = ET.fromstring(data)
    entry = root.find("atom:entry", ARXIV_NS)
    if entry is None:
        return None
    paper_id = (entry.findtext("atom:id", default="", namespaces=ARXIV_NS) or "").rsplit("/abs/", 1)[-1]
    return {
        "id": paper_id,
        "title": " ".join((entry.findtext("atom:title", default="", namespaces=ARXIV_NS) or "").split()),
        "authors": [a.findtext("atom:name", default="", namespaces=ARXIV_NS) or ""
                    for a in entry.findall("atom:author", ARXIV_NS)],
        "published": (entry.findtext("atom:published", default="", namespaces=ARXIV_NS) or "")[:10],
        "journal_ref": entry.findtext("arxiv:journal_ref", default="", namespaces=ARXIV_NS) or None,
        "doi": entry.findtext("arxiv:doi", default="", namespaces=ARXIV_NS) or None,
        "abstract": "",
    }


# ---------------------------------------------------------------- name utils

def norm(s: str) -> str:
    """Lowercase, strip diacritics and non-alphanumerics for fuzzy compare."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def surname(name: str) -> str:
    """Extract a surname, tolerating 'Angela Kou' and 'Kou, Angela' forms."""
    name = (name or "").strip()
    if "," in name:
        name = name.split(",")[0]
    parts = name.split()
    return norm(parts[-1]) if parts else ""


def norm_page(p) -> str:
    """Normalize an article number: '030103(R)' -> '030103', '020201(1)' -> '020201'."""
    p = re.sub(r"\(.*\)$", "", (p or "").strip().lower())
    return re.sub(r"[^0-9]", "", p)


def year_of(date_str: str):
    try:
        return int((date_str or "")[:4])
    except Exception:
        return None


def crossref_year(item):
    for key in ("published-print", "published-online", "issued", "created"):
        parts = item.get(key, {}).get("date-parts")
        if parts and parts[0] and parts[0][0]:
            try:
                return int(parts[0][0])
            except Exception:
                pass
    return None


def parse_journal_ref(text):
    """Parse 'PRX Quantum 5, 040314 (2024)' -> dict(journal, volume, page, year)."""
    m = JREF_RE.match((text or "").strip())
    if not m:
        return None
    return {k: v.strip() for k, v in m.groupdict().items()}


# -------------------------------------------------------------- crossref

def crossref_query(biblio: str, rows: int, mailto: str):
    params = {"query.bibliographic": biblio, "rows": rows, "select": SELECT}
    if mailto:
        params["mailto"] = mailto
    url = "{}?{}".format(CROSSREF_API, urllib.parse.urlencode(params))
    data = fetch_json(url)
    return (data or {}).get("message", {}).get("items") or []


def crossref_query_union(query_parts, rows: int, mailto: str):
    """Run several queries, merge candidates, dedupe by DOI.

    query_parts: list of either 'query.bibliographic=...' or 'filter=...'
    strings. Used by the journal_ref path because Crossref's plain
    bibliographic search performs badly on 'journal abbrev + volume + article
    number', while the precise article-number filter is far more reliable.
    """
    items_by_doi = {}
    for part in query_parts:
        params = {"rows": rows, "select": SELECT}
        if part.startswith("filter="):
            params["filter"] = part[len("filter="):]
        else:
            params["query.bibliographic"] = part[len("query.bibliographic="):]
        if mailto:
            params["mailto"] = mailto
        url = "{}?{}".format(CROSSREF_API, urllib.parse.urlencode(params))
        data = fetch_json(url)
        for item in (data or {}).get("message", {}).get("items") or []:
            items_by_doi[item.get("DOI")] = item
    return list(items_by_doi.values())


def crossref_work(doi: str, mailto: str):
    # NOTE: the single-work route /works/{DOI} does NOT support the select
    # parameter (returns HTTP 400); fetch the full record instead.
    params = {}
    if mailto:
        params["mailto"] = mailto
    url = "{}/{}?{}".format(CROSSREF_API, urllib.parse.quote(doi, safe="/"), urllib.parse.urlencode(params))
    data = fetch_json(url)
    return (data or {}).get("message") if data else None


# ---------------------------------------------------------------- verify

def verify(record, item, jref, require_tuple):
    """Check a Crossref candidate against the arXiv record.

    Returns (ok, notes): ok True -> accept; False -> reject (author mismatch);
    None -> borderline (author ok but year/volume/page off) -> needs human review.
    """
    notes = []
    authors = record.get("authors") or []
    a1 = surname(authors[0]) if authors else ""
    ia = item.get("author") or [{}]
    i1 = surname(ia[0].get("family") or ia[0].get("name") or "") if ia else ""
    author_ok = bool(a1) and a1 == i1
    if not author_ok:
        notes.append("第一作者姓氏不匹配 (arXiv: {} vs Crossref: {})".format(a1 or "?", i1 or "?"))

    y_arxiv = year_of(record.get("published"))
    y_item = crossref_year(item)
    year_ok = y_arxiv and y_item is not None and abs(y_item - y_arxiv) <= 1
    if not year_ok:
        notes.append("年份差>1年 (arXiv: {} vs Crossref: {})".format(y_arxiv, y_item))

    tuple_ok = True
    if jref and jref.get("volume"):
        v_ok = norm(str(item.get("volume") or "")) == norm(str(jref["volume"]))
        p_ok = norm_page(item.get("page") or "") == norm_page(jref.get("page") or "")
        if not v_ok:
            notes.append("卷不匹配 (arXiv: {} vs Crossref: {})".format(jref["volume"], item.get("volume") or "?"))
        if not p_ok:
            notes.append("页码不匹配 (arXiv: {} vs Crossref: {})".format(jref.get("page") or "?", item.get("page") or "?"))
        # Volume or page matching is enough for the tuple check; article
        # numbers may be formatted differently across databases.
        tuple_ok = v_ok or p_ok

    if not author_ok:
        return False, notes
    if not year_ok:
        return None, notes
    if require_tuple and jref and jref.get("volume") and not tuple_ok:
        return None, notes
    return True, []


def pick_candidate(record, items, jref, require_tuple, source):
    """First verified candidate wins; else keep the first borderline one."""
    first_suspect = None
    for item in items:
        ok, notes = verify(record, item, jref, require_tuple)
        doi = item.get("DOI")
        if ok:
            scope = "作者/年份/卷页" if (jref and jref.get("volume")) else "第一作者/年份"
            return {"doi": doi, "source": source, "status": "verified",
                    "note": "Crossref {} 校验通过".format(scope)}
        if ok is None and first_suspect is None:
            first_suspect = (doi, notes)
    if first_suspect:
        doi, notes = first_suspect
        return {"doi": doi, "source": source, "status": "suspect",
                "note": "作者吻合但 {}；候选 DOI 未自动接受，须人工复核".format("；".join(notes))}
    return None


# --------------------------------------------------------------- resolve

def resolve_native(record, mailto):
    """Priority 1: arXiv native doi field (author-filled, most trustworthy)."""
    doi = record["doi"]
    item = crossref_work(doi, mailto)
    if item is None:
        return {"doi": doi, "source": "arxiv-native", "status": "warning",
                "note": "arXiv 原生 DOI；Crossref 校验失败（DOI 无效或网络异常），以 arXiv 记录为准"}
    ok, notes = verify(record, item, None, False)
    if ok:
        return {"doi": doi, "source": "arxiv-native", "status": "verified",
                "note": "原生 DOI，第一作者/年份与 arXiv 记录吻合"}
    return {"doi": doi, "source": "arxiv-native", "status": "warning",
            "note": "原生 DOI；注意：" + "；".join(notes)}


def resolve_one(record, rows, mailto):
    base = {"id": record.get("id"), "title": record.get("title")}

    # Priority 1: arXiv native DOI field.
    if record.get("doi"):
        return dict(base, **resolve_native(record, mailto))

    # Priority 2: journal_ref tuple -> Crossref.
    jref = parse_journal_ref(record.get("journal_ref") or "")
    if jref:
        page = jref.get("page") or ""
        queries = []
        if re.fullmatch(r"\d+", page):
            # Article numbers are unique; the precise filter beats fuzzy search.
            queries.append("filter=article-number:{}".format(page))
        queries.append("query.bibliographic={} {} {}".format(jref["journal"], jref["volume"], page))
        items = crossref_query_union(queries, rows, mailto)
        res = pick_candidate(record, items, jref, True, "journal-ref")
        if res:
            return dict(base, **res)

    # Priority 3: title + first author + year fallback.
    authors = record.get("authors") or []
    a1 = surname(authors[0]) if authors else ""
    y = year_of(record.get("published"))
    biblio = "{} {} {}".format(record.get("title") or "", a1, y or "")
    items = crossref_query(biblio, rows, mailto)
    res = pick_candidate(record, items, None, False, "title-fallback")
    if res:
        return dict(base, **res)

    # Priority 4: preprint only.
    return dict(base, doi=None, source="none", status="none",
                note="仅 arXiv 预印本，无正式发表 DOI；引用时使用 arXiv ID")


# ----------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="*", help="arXiv IDs to resolve, e.g. 2401.08762")
    parser.add_argument("--json", metavar="FILE", help="read records from search_arxiv.py JSON output")
    parser.add_argument("--out", metavar="FILE", help="write results as JSON to FILE")
    parser.add_argument("--rows", type=int, default=5, help="Crossref candidates per query (default 5)")
    parser.add_argument("--mailto", default="", help="contact email for the Crossref polite pool")
    args = parser.parse_args(argv)

    if not args.ids and not args.json:
        parser.error("provide at least one arXiv ID or --json FILE")

    records = []
    if args.json:
        try:
            with open(args.json, "r", encoding="utf-8") as fh:
                records.extend(json.load(fh))
        except Exception as exc:
            print("Failed to read --json file: {}".format(exc), file=sys.stderr)
            return 2
    seen = {r.get("id") for r in records if r.get("id")}
    for arxiv_id in args.ids:
        meta = fetch_arxiv_meta(arxiv_id)
        if meta is None:
            print("Could not fetch arXiv metadata for {}".format(arxiv_id), file=sys.stderr)
            continue
        if meta["id"] not in seen:
            records.append(meta)
            seen.add(meta["id"])

    if not records:
        print("No records to resolve.", file=sys.stderr)
        return 1

    results = [resolve_one(r, args.rows, args.mailto) for r in records]

    for i, res in enumerate(results, 1):
        doi = res.get("doi") or "—"
        print("[{:2}] {} - {}".format(i, res.get("id"), res.get("title")))
        print("     DOI: {} | 来源: {} | 状态: {}".format(doi, res.get("source"), res.get("status")))
        if res.get("note"):
            print("     说明: {}".format(res["note"]))
        print()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
        print("Saved results: {}".format(args.out), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
