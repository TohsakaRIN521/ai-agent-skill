#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download arXiv TeX sources for given arXiv IDs and extract them.

Fetches https://arxiv.org/e-print/<id>, detects the format (tar archive,
gzipped TeX file, or plain TeX) and unpacks each paper into its own
subdirectory under --out.
"""
import argparse
import gzip
import os
import sys
import tarfile
import time
import urllib.request

EPRINT_URL = "https://arxiv.org/e-print/{}"
TEX_SUFFIXES = (".tex", ".ltx", ".bbl")


def safe_extract(tar: tarfile.TarFile, path: str) -> None:
    base = os.path.abspath(path)
    for member in tar.getmembers():
        dest = os.path.abspath(os.path.join(base, member.name))
        if not dest.startswith(base + os.sep):
            raise RuntimeError("unsafe archive member: {}".format(member.name))
    if hasattr(tarfile, "data_filter"):
        tar.extractall(path, filter="data")
    else:
        tar.extractall(path)


def looks_like_tex(data: bytes) -> bool:
    return data[:2048].lstrip().startswith(b"\\") or b"\\begin{" in data[:4096]


def collect_tex(root: str):
    found = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.lower().endswith(TEX_SUFFIXES):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def unpack(data: bytes, paper_id: str, outdir: str):
    target = os.path.join(outdir, paper_id)
    os.makedirs(target, exist_ok=True)
    raw = os.path.join(target, paper_id + ".src")
    with open(raw, "wb") as fh:
        fh.write(data)

    # 1) tar archive (possibly gzip/bzip2/xz compressed)
    try:
        with tarfile.open(raw, mode="r:*") as tar:
            safe_extract(tar, target)
        extracted = collect_tex(target)
        if extracted:
            return extracted
    except tarfile.TarError:
        pass

    # 2) gzip-compressed single file (.tex.gz)
    if data[:2] == b"\x1f\x8b":
        try:
            inner = gzip.decompress(data)
            if looks_like_tex(inner):
                tex_path = os.path.join(target, paper_id + ".tex")
                with open(tex_path, "wb") as fh:
                    fh.write(inner)
                return [tex_path]
        except (OSError, EOFError):
            pass

    # 3) plain TeX source
    if looks_like_tex(data):
        tex_path = os.path.join(target, paper_id + ".tex")
        with open(tex_path, "wb") as fh:
            fh.write(data)
        return [tex_path]

    # 4) unknown format (e.g. PDF-only submission)
    return []


def download(paper_id: str, outdir: str, retries: int = 3):
    url = EPRINT_URL.format(paper_id)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "arxiv-paper-completion/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            tex_files = unpack(data, paper_id, outdir)
            if tex_files:
                print(
                    "[OK] {} -> {} TeX file(s) under {}".format(
                        paper_id, len(tex_files), os.path.join(outdir, paper_id)
                    )
                )
            else:
                print("[WARN] {} downloaded but no .tex found (PDF-only?)".format(paper_id))
            return
        except Exception as exc:
            last_err = exc
            time.sleep(3 * (attempt + 1))
    print("[FAIL] {}: {}".format(paper_id, last_err), file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="+", help="arXiv IDs, e.g. 2401.00001")
    parser.add_argument("--out", default="tex_sources", help="output directory (default: tex_sources)")
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    for paper_id in args.ids:
        download(paper_id, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
