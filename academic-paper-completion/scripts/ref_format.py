# -*- coding: utf-8 -*-
"""Batch reformat of thebibliography entries in a .tex file.

Turns entries like
    \\bibitem{key} \\href{DOI}{Authors, Phys. Rev. A \\textbf{82}, 010103(R) (2010).}
into reference-file style
    \\bibitem{key} Authors, Title, \\href{DOI}{Phys. Rev. A 82, 010103(R) (2010)}.

Features:
- Parses \\begin{thebibliography}...\\end{thebibliography} (also \\begin{references}).
- Optionally fetches official titles from the Crossref API by DOI
  (much faster than per-entry web search) and strips <mml:math> markup.
- Options: --titles / --link {all,journal,none} / --apply / --out / --keep-bold.

Usage:
  python ref_format.py paper.tex --titles --out new_refs.txt          # preview
  python ref_format.py paper.tex --titles --apply                     # backup+replace
"""
import re, sys, json, time, unicodedata, urllib.request, argparse
from datetime import datetime

# journal-name pattern, longest alternatives first
JRNL = re.compile(
    r"(?:Phys\. Rev\. (?:Lett\.|Research|A|B|X)|Adv\. Phys\.|Rep\. Prog\. Phys\.|"
    r"Front\. Phys\.|Nat\. Rev\. Phys\.|Nat\. Phys\.|Rev\. Mod\. Phys\.|Sci\. Rep\.|"
    r"Eur\. Phys\. J\. D|New J\. Phys\.|Commun\. Pure Appl\. Math\.|Phys\. Lett\. A|"
    r"Phys\. Rep\.|Nature|Phys\. Rev\.)"
)
BIB_SPLIT = re.compile(r"(?=\\bibitem\{)")
BIB_ITEM = re.compile(r"\\bibitem\{([^}]+)\}(.*)$", re.S)
HREF = re.compile(r"\\href\{(https?://[^}]+)\}\{(.*)\}(?:\.)?\s*$", re.S)
TEXTBF = re.compile(r"\\textbf\{([^}]*)\}")
MML = re.compile(r"<mml:math.*?</mml:math>", re.S)
WS = re.compile(r"\s+")

# common latin accents -> LaTeX escapes
ACCENT = {
    ord("á"): r"\'a", ord("à"): r"\`a", ord("â"): r"\^a", ord("ä"): r'\"a', ord("ã"): r"\~a",
    ord("é"): r"\'e", ord("è"): r"\`e", ord("ê"): r"\^e", ord("ë"): r'\"e',
    ord("í"): r"\'i", ord("ì"): r"\`i", ord("î"): r"\^i", ord("ï"): r'\"i',
    ord("ó"): r"\'o", ord("ò"): r"\`o", ord("ô"): r"\^o", ord("ö"): r'\"o', ord("õ"): r"\~o",
    ord("ú"): r"\'u", ord("ù"): r"\`u", ord("û"): r"\^u", ord("ü"): r'\"u',
    ord("ý"): r"\'y", ord("ÿ"): r'\"y',
    ord("ç"): r"\c{c}", ord("ñ"): r"\~n",
    ord("Á"): r"\'A", ord("É"): r"\'E", ord("Í"): r"\'I", ord("Ó"): r"\'O", ord("Ú"): r"\'U",
    ord("Ä"): r'\"A', ord("Ö"): r'\"O', ord("Ü"): r'\"U',
    ord("\u2013"): "--", ord("\u2014"): "---",
}

def latex_escape(s):
    """Convert common unicode chars to LaTeX escapes."""
    return s.translate(ACCENT)

def clean_title(t):
    """Remove MathML/TeX-math markup, restore spacing (e.g. 'PT -symmetry' -> 'PT-symmetry')."""
    t = MML.sub(" PT ", t)                     # <mml:math> -> placeholder with spaces
    t = re.sub(r"\$\$.*?\$\$", " PT ", t)      # $$...$$ TeX math (e.g. \mathcal{PT}) -> placeholder
    t = WS.sub(" ", t)                         # collapse whitespace/newlines
    t = re.sub(r"\s+([\-.,;:])", r"\1", t)     # 'PT -symmetric' -> 'PT-symmetric'
    t = re.sub(r"(\-)\s+", r"\1", t)           # 'anti- PT' -> 'anti-PT' (hyphen only)
    t = t.strip().rstrip(".").strip()
    return latex_escape(t)

def fetch_title(doi, mailto="research@example.com"):
    """Official title from Crossref by DOI; '' on failure (3 attempts)."""
    url = f"https://api.crossref.org/works/{doi}"
    req = urllib.request.Request(url, headers={"User-Agent": f"ref-format/1.0 (mailto:{mailto})"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.load(r)["message"]
            t = d.get("title") or [""]
            return clean_title(t[0])
        except Exception:
            time.sleep(1.0 + attempt)
    print(f"!! title fetch failed for {doi}", file=sys.stderr)
    return ""

def split_authors_journal(body):
    """Split 'Authors, Journal Vol, Page (Year).' into (authors, journal_info)."""
    jm = JRNL.search(body)
    if not jm:
        return body, None
    authors = body[: jm.start()].strip().rstrip(",").strip()
    jinfo = body[jm.start():].strip()
    jinfo = jinfo[:-1].strip() if jinfo.endswith(".") else jinfo
    return authors, jinfo

def parse_bibitems(src):
    """Parse thebibliography block -> list of dicts {key, doi, body}."""
    pat = re.compile(r"\\begin\{(thebibliography|references)\}.*?\\end\{\1\}", re.S)
    m = pat.search(src)
    if not m:
        raise SystemExit("!! no thebibliography/references block found")
    block = m.group(0)
    block_body = re.sub(r"\\end\{(thebibliography|references)\}\s*$", "", block, flags=re.S)
    items = []
    for seg in BIB_SPLIT.split(block_body):
        im = BIB_ITEM.match(seg)
        if not im:
            continue
        key, rest = im.group(1), im.group(2)
        rest_s = rest.strip()
        hm = HREF.search(rest_s)
        if hm:
            pre = rest_s[: hm.start()].strip().rstrip(",").strip()
            items.append({"key": key, "doi": hm.group(1), "body": hm.group(2), "pre": pre})
        else:
            items.append({"key": key, "doi": None, "body": rest_s, "pre": ""})
    return m, block, items

def reformat(items, titles=False, link="journal", no_bold=True):
    out = []
    for it in items:
        # already target format (authors/title outside the \href): keep unchanged
        if it["pre"]:
            out.append(f"\\bibitem{{{it['key']}}} {it['pre']}, \\href{{{it['doi']}}}{{{it['body'].rstrip('.')}}}.")
            continue
        body = it["body"]
        if no_bold:
            body = TEXTBF.sub(r"\1", body)
        authors, jinfo = split_authors_journal(body)
        if jinfo is None:                      # cannot identify journal: keep as-is
            out.append(f"\\bibitem{{{it['key']}}} {body}")
            continue
        title = ""
        if titles and it["doi"]:
            title = fetch_title(it["doi"])
            time.sleep(0.15)
        if title:
            head = f"{authors}, {title},"
        else:
            head = f"{authors},"
        if link == "journal" and it["doi"]:
            out.append(f"\\bibitem{{{it['key']}}} {head} \\href{{{it['doi']}}}{{{jinfo}}}.")
        elif link == "all" and it["doi"]:
            out.append(f"\\bibitem{{{it['key']}}} \\href{{{it['doi']}}}{{{head} {jinfo}}}.")
        else:
            out.append(f"\\bibitem{{{it['key']}}} {head} {jinfo}.")
    return out

def main():
    ap = argparse.ArgumentParser(description="Reformat thebibliography entries")
    ap.add_argument("tex", help="path to .tex file")
    ap.add_argument("--titles", action="store_true", help="fetch official titles from Crossref by DOI")
    ap.add_argument("--link", choices=["all", "journal", "none"], default="journal",
                    help="hyperlink placement: all=whole entry, journal=journal info only, none=no links")
    ap.add_argument("--keep-bold", action="store_true", help="keep \\textbf{} volume bold (default: strip it)")
    ap.add_argument("--apply", action="store_true", help="backup and replace the block in the tex file")
    ap.add_argument("--out", help="write new entries to this file instead of stdout")
    ap.add_argument("--no-bak", action="store_true", help="skip timestamped backup with --apply")
    args = ap.parse_args()

    src = open(args.tex, encoding="utf-8-sig").read()
    m, block, items = parse_bibitems(src)
    print(f"parsed {len(items)} bibitems")

    new_lines = reformat(items, titles=args.titles, link=args.link, no_bold=not args.keep_bold)
    hdr = block[: block.index("\n")].strip()
    if "thebibliography" not in hdr:
        hdr = "\\begin{thebibliography}{99}"
    new_block = hdr + "\n" + "\n".join(new_lines) + "\n\\end{thebibliography}"

    if args.apply:
        if not args.no_bak:
            bak = args.tex[:-4] + f"_bak_{datetime.now():%Y%m%d_%H%M%S}_ref.tex"
            open(bak, "w", encoding="utf-8", newline="\n").write(src)
            print("backup ->", bak)
        new_src = src[: m.start()] + new_block + src[m.end():]
        open(args.tex, "w", encoding="utf-8", newline="\n").write(new_src)
        print("applied to", args.tex, "| run verify_compile.py afterwards")
    else:
        text = "\n".join(new_lines)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text + "\n")
            print("preview written ->", args.out)
        else:
            print("\n".join(new_lines))

if __name__ == "__main__":
    main()
