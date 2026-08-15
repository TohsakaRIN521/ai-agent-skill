# -*- coding: utf-8 -*-
r"""Batch verification of thebibliography entries against Crossref by DOI.

Parses the \begin{thebibliography} block of a .tex file, extracts each
\bibitem{key} entry with its DOI and locally-printed journal info
(\href{DOI}{Journal Vol, Page (Year)}), queries Crossref for the
authoritative record, and classifies every entry as
    OK  /  SUSPECT  /  WRONG
with per-field mismatch details.  Never modifies the tex file.

Optional --cite-dir DIR additionally lists arXiv source folders (\d{4}.\d{4,5})
and maps each to the bibliography entry whose Crossref title matches the
arXiv title, producing a "source folder <-> bibitem" correspondence table.

Usage:
  python verify_refs.py paper.tex                  # table to stdout
  python verify_refs.py paper.tex --out report.md  # write verification report
  python verify_refs.py paper.tex --cite-dir ../cite --out report.md
  python verify_refs.py paper.tex --offline        # no network lookups
"""
import re, sys, json, time, argparse, unicodedata, urllib.request, os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ref_format import parse_bibitems, split_authors_journal, TEXTBF  # reuse parsers

UA = {"User-Agent": "verify-refs/1.0 (mailto:research@example.com)"}
JINFO = re.compile(r"^(.*?)\s+(\d+),\s*(\S+?)\s*\((\d{4})\)\s*\.?$")
NUM_FOLDER = re.compile(r"^(\d{4}\.\d{4,5})$")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def tokens(s):
    out = set()
    for w in re.findall(r"[A-Za-z0-9]+", s):
        w = w.lower()
        for i in range(1, min(3, len(w)) + 1):
            out.add(w[:i])
    return out


def jmatch(a, b):
    """Fuzzy journal-name match via token-prefix containment."""
    ta, tb = tokens(a), tokens(b)
    return bool(ta and tb and (ta <= tb or tb <= ta))


def first_author(s):
    s = norm(s)
    s = re.sub(r"\s+et al\.?.*$", "", s)
    first = s.split(",")[0].strip()
    fam = first.split()[-1] if first.split() else ""
    return re.sub(r"[^a-z]", "", fam)


def page_norm(p):
    p = (p or "").strip()
    p = p.split("-")[0].split("\u2013")[0]          # keep start page of a range
    return re.sub(r"[\s()]", "", p).lower()


def get(url):
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception:
            time.sleep(1.0 + attempt)
    return None


def crossref(doi):
    d = get("https://api.crossref.org/works/" + doi)
    if not d or "message" not in d:
        return None
    m = d["message"]
    year = ""
    for k in ("issued", "published-print", "published-online"):
        dp = m.get(k, {}).get("date-parts") or []
        if dp and dp[0]:
            year = str(dp[0][0])
            break
    auth = m.get("author") or []
    fam = norm(auth[0].get("family", "")) if auth else ""
    return {
        "title": (m.get("title") or [""])[0],
        "journal": (m.get("container-title") or [""])[0],
        "volume": str(m.get("volume") or ""),
        "page": page_norm(m.get("page") or m.get("article-number") or ""),
        "year": year,
        "family": re.sub(r"[^a-z]", "", fam),
    }


def parse_local(body):
    b = TEXTBF.sub(r"\1", body).strip()
    m = JINFO.match(b)
    if not m:
        return None
    return {"journal": m.group(1), "volume": m.group(2),
            "page": page_norm(m.group(3)), "year": m.group(4)}


def classify(local, cr, doi, fam_local, offline):
    if not local:
        return "存疑", "本地条目格式无法解析（期刊/卷/页码/年份）"
    if cr is None:
        if offline:
            return "存疑", "--offline 模式未联网核验" + (f"（{doi}）" if doi else "（无 DOI）")
        return "存疑", "Crossref 按 DOI 核验失败" + (f"（{doi}）" if doi else "（无 DOI）")
    diffs = []
    if not jmatch(local["journal"], cr["journal"]):
        diffs.append("期刊: " + local["journal"] + " vs Crossref " + cr["journal"])
    if local["volume"] != cr["volume"]:
        diffs.append("卷: " + local["volume"] + " vs " + cr["volume"])
    if local["page"] and cr["page"] and local["page"] != cr["page"]:
        diffs.append("页码/文章号: " + local["page"] + " vs " + cr["page"])
    if local["year"] != cr["year"]:
        diffs.append("年份: " + local["year"] + " vs " + cr["year"])
    if fam_local and cr["family"] and fam_local != cr["family"]:
        diffs.append("首作者: " + fam_local + " vs " + cr["family"])
    if not diffs:
        return "OK", "DOI 与期刊/卷/页码/年份/首作者一致"
    hard = (not jmatch(local["journal"], cr["journal"]) and local["year"] != cr["year"])
    return ("不实" if hard else "存疑"), "; ".join(diffs)


def arxiv_titles(ids):
    if not ids:
        return {}
    url = "https://export.arxiv.org/api/query?id_list=" + ",".join(ids) + "&max_results=60"
    d = get(url)
    if not d:
        return None
    out = {}
    for e in d.get("entry", []):
        aid = (e.get("id") or "").rstrip("/").split("/")[-1]
        out[aid] = re.sub(r"\s+", " ", e.get("title", "")).strip()
    return out


def title_key(t):
    return re.sub(r"[^a-z0-9]", "", norm(t))


def main():
    ap = argparse.ArgumentParser(description="Verify thebibliography entries via Crossref DOI")
    ap.add_argument("tex", help="path to .tex file")
    ap.add_argument("--out", help="write report to this file (default: stdout)")
    ap.add_argument("--cite-dir", help="arXiv source folder to map folders <-> bibitems")
    ap.add_argument("--offline", action="store_true", help="skip all network lookups")
    args = ap.parse_args()

    src = open(args.tex, encoding="utf-8-sig").read()
    _, _, items = parse_bibitems(src)
    print("parsed", len(items), "bibitems")

    rows, notes = [], []
    for it in items:
        doi = it["doi"]
        local = parse_local(it["body"]) if it["body"] else None
        authors = it["pre"] or (split_authors_journal(it["body"])[0] if it["body"] else "")
        fam_local = first_author(authors)
        cr = None
        if doi and not args.offline:
            cr = crossref(doi)
            time.sleep(0.1)
        status, reason = classify(local, cr, doi, fam_local, args.offline)
        journal = local["journal"] if local else (cr["journal"] if cr else "")
        rows.append((it["key"], journal, status, reason, doi or "", cr or None))
        if status != "OK":
            notes.append("- " + it["key"] + "（" + journal + "）: " + reason)

    cite_rows = []
    if args.cite_dir and not args.offline:
        ids = sorted(d for d in os.listdir(args.cite_dir)
                     if os.path.isdir(os.path.join(args.cite_dir, d)) and NUM_FOLDER.match(d))
        at = arxiv_titles(ids)
        if at is None:
            notes.append("- arXiv 源码标题获取失败（联网问题），cite 对应表未生成")
            ids, at = [], {}
        titles = {}
        for it in items:
            t = ""
            if it["pre"] and "," in it["pre"]:
                t = it["pre"].split(",")[1].strip()
            for rw in rows:
                if rw[0] == it["key"] and rw[5]:
                    t = t or rw[5]["title"]
            titles[it["key"]] = title_key(t or "")
        for aid in ids:
            tk = title_key(at.get(aid, ""))
            hit = next((k for k, v in titles.items()
                        if v and (v == tk or (len(v) > 8 and (v in tk or tk in v)))), None)
            cite_rows.append((aid, hit if hit else "—", "OK" if hit else "未匹配"))

    n_ok = sum(1 for r in rows if r[2] == "OK")
    L = []
    L.append("# 参考文献真实性核验报告")
    L.append("")
    L.append("- 核验对象: " + args.tex + " 内全部 " + str(len(rows)) + " 条参考文献")
    L.append("- 核验方式: Crossref API 按 DOI 批量核验" + (" + arXiv 源码对应" if cite_rows else ""))
    L.append("- 核验日期: " + date.today().isoformat())
    L.append("- 结论: " + str(n_ok) + "/" + str(len(rows)) + " 条字段全部一致；其余见逐条表与说明")
    L.append("")
    L.append("## 逐条核验结果")
    L.append("")
    L.append("| 引用键 | 论文条目(期刊/卷/页,年份) | 状态 | 说明 |")
    L.append("|---|---|---|---|")
    for key, journal, status, reason, doi, cr in rows:
        L.append("| " + key + " | " + journal + " | " + status + " | " + reason + " |")
    if cite_rows:
        L.append("")
        L.append("## cite/ 源码文件夹 ↔ 引用条目对应")
        L.append("")
        L.append("| arXiv 文件夹 | 引用键 | 状态 |")
        L.append("|---|---|---|")
        for aid, key, st in cite_rows:
            L.append("| " + aid + " | " + key + " | " + st + " |")
    L.append("")
    L.append("## 需要特别说明的条目")
    L.append("")
    if notes:
        L.extend(notes)
    else:
        L.append("- 无")
    L.append("")
    L.append("## 结论")
    L.append("")
    L.append("- 逐条按 DOI 与 Crossref 权威记录比对；'存疑' 条目请人工复核或换 ADS/INSPIRE 二次确认。")
    text = "\n".join(L)

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        print("report written ->", args.out)
    else:
        for key, journal, status, reason, doi, cr in rows:
            print(status, key, "|", journal, "|", reason)
        if cite_rows:
            print()
            print("[cite-dir]")
            for aid, key, st in cite_rows:
                print("  ", aid, "->", key, st)


if __name__ == "__main__":
    main()
