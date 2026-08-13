#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safely apply exact string replacements to a LaTeX file.

Usage:
  python scripts/patch_tex.py <file.tex> <patches.json> [--backup-dir DIR] [--dry-run]

patches.json:
{
  "patches": [
    {"old": "exact text ...", "new": "replacement ...", "expect": 1}
  ]
}

Behavior:
- Reads the target file as UTF-8-sig and preserves CRLF/LF line endings.
- Each 'old' must occur exactly 'expect' times (default 1); otherwise aborts
  before writing anything.
- Creates a timestamped backup next to the file (or in --backup-dir) before writing.
- Writes back as UTF-8 with the original line-ending style preserved.
"""
import argparse
import datetime
import io
import json
import os
import shutil
import sys


def detect_nl(text):
    return "\r\n" if "\r\n" in text else "\n"


def candidates(s, nl):
    out = [s]
    if "\n" in s:
        out.append(s.replace("\n", nl))
    return list(dict.fromkeys(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="path to the .tex file")
    ap.add_argument("patches_json", help="path to JSON with 'patches' list")
    ap.add_argument("--backup-dir", default=None,
                    help="directory for the backup copy (default: same dir as target)")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate only; write nothing")
    args = ap.parse_args()

    with open(args.patches_json, "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    patches = spec.get("patches")
    if not isinstance(patches, list) or not patches:
        sys.exit("ERROR: patches.json must contain a non-empty 'patches' list")

    with io.open(args.target, "r", encoding="utf-8-sig", newline="") as fh:
        data = fh.read()
    nl = detect_nl(data)

    resolved = []
    for i, p in enumerate(patches):
        old = p["old"]
        new = p.get("new", "")
        expect = int(p.get("expect", 1))
        hit = None
        counts = []
        for c in candidates(old, nl):
            n = data.count(c)
            counts.append(n)
            if n == expect:
                hit = c
                break
        if hit is None:
            detail = "; ".join("found %d" % n for n in counts)
            sys.exit("ERROR: patch #%d expected %d occurrence(s), %s"
                     % (i, expect, detail))
        new_out = new
        if "\n" in new:
            new_out = new.replace("\n", nl)
        resolved.append((hit, new_out, expect))
        print("OK #%d: %d occurrence(s) matched" % (i, expect))

    if args.dry_run:
        print("DRY RUN: validation passed; no changes written.")
        return 0

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.backup_dir:
        os.makedirs(args.backup_dir, exist_ok=True)
        backup = os.path.join(args.backup_dir,
                              os.path.basename(args.target) + ".bak_" + ts)
    else:
        backup = args.target + ".bak_" + ts
    shutil.copy2(args.target, backup)
    print("Backup:", backup)

    for old, new, _ in resolved:
        data = data.replace(old, new)

    with io.open(args.target, "w", encoding="utf-8", newline="") as fh:
        fh.write(data)
    print("Updated:", args.target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
