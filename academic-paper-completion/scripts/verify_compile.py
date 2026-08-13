#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile a LaTeX file in an isolated directory and report on the log.

Usage:
  python verify_compile.py path/to/paper.tex [--work DIR]

Copies the .tex plus its sibling figures/ directory and common resource files
(*.png *.pdf *.eps *.jpg *.jpeg *.bib *.bbl *.sty *.cls) into a work directory,
runs `latexmk -pdf` there (without touching the source directory), then greps the
log for LaTeX errors, undefined references/citations, oversized floats, and
overfull boxes. The compiled PDF stays in the work directory.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Graphics and class/package files are always copied. Bibliography files are
# handled separately below: a .bib is only needed by BibTeX-based documents
# (\bibliography / \addbibresource), and a .bbl is a generated artifact that
# latexmk regenerates itself, so it is never copied (copying a stale .bbl can
# trigger a spurious bibtex run and change the output).
GRAPHIC_EXTS = (".png", ".pdf", ".eps", ".jpg", ".jpeg", ".sty", ".cls")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tex", help="path to the .tex file to verify")
    ap.add_argument("--work", metavar="DIR", help="work dir (default: a fresh temp dir)")
    args = ap.parse_args(argv)

    tex = os.path.abspath(args.tex)
    if not os.path.isfile(tex):
        sys.exit("ERROR: not a file: {}".format(tex))
    src_dir = os.path.dirname(tex)
    base = os.path.basename(tex)

    work = os.path.abspath(args.work) if args.work else tempfile.mkdtemp(prefix="tex_verify_")
    os.makedirs(work, exist_ok=True)

    with open(tex, "r", encoding="utf-8", errors="replace") as fh:
        tex_src = fh.read()
    needs_bib = bool(re.search(r"\\bibliography\{|\\addbibresource", tex_src))
    copy_exts = GRAPHIC_EXTS + ((".bib",) if needs_bib else ())

    shutil.copy2(tex, os.path.join(work, base))
    figures = os.path.join(src_dir, "figures")
    if os.path.isdir(figures):
        shutil.copytree(figures, os.path.join(work, "figures"))
    for name in os.listdir(src_dir):
        if name.lower().endswith(copy_exts):
            shutil.copy2(os.path.join(src_dir, name), os.path.join(work, name))

    latexmk = shutil.which("latexmk")
    if not latexmk:
        sys.exit("ERROR: latexmk not found on PATH (install TeX Live / MiKTeX).")

    print("Work dir: {}".format(work))
    print("Compiling {} (progress streams live below) ...".format(base))
    # Stream latexmk's output instead of buffering it: a full compile can take
    # minutes on a cold TeX install, and a silent pipe looks frozen.
    proc = subprocess.run(
        [latexmk, "-pdf", "-interaction=nonstopmode", "-halt-on-error", base],
        cwd=work,
    )
    if proc.returncode != 0:
        print("RESULT: COMPILE FAILED (exit {})".format(proc.returncode))
        return 1

    log_path = os.path.join(work, base.rsplit(".", 1)[0] + ".log")
    if not os.path.isfile(log_path):
        logs = [os.path.join(work, f) for f in os.listdir(work) if f.endswith(".log")]
        if not logs:
            print("RESULT: COMPILE OK (no .log found)")
            return 0
        log_path = logs[0]

    log = open(log_path, "r", encoding="utf-8", errors="replace").read()

    errors = len(re.findall(r"^!.*", log, re.M))
    latex_err = len(re.findall(r"LaTeX Error", log))
    undefined = len(re.findall(r"undefined", log, re.I))
    float_too_large = len(re.findall(r"Float too large", log))
    overfull = len(re.findall(r"Overfull", log))

    print("\n--- log checks ---")
    print("  {:>3}  {}  compile errors (lines starting with '!')".format(errors, "ERROR" if errors else "ok"))
    print("  {:>3}  {}  LaTeX Error".format(latex_err, "ERROR" if latex_err else "ok"))
    print("  {:>3}  {}  undefined references/citations".format(undefined, "CHECK" if undefined else "ok"))
    print("  {:>3}  {}  Float too large".format(float_too_large, "CHECK" if float_too_large else "ok"))
    print("  {:>3}  {}  Overfull boxes (cosmetic)".format(overfull, "WARN" if overfull else "ok"))

    problems = [ln.strip() for ln in log.splitlines()
                if ("undefined" in ln.lower() or "latex error" in ln.lower()
                    or "float too large" in ln.lower() or ln.strip().startswith("!"))]
    if problems:
        print("\n--- detail ---")
        for ln in problems[:12]:
            print("   ", ln)

    pages = re.search(r"Output written on .*\((\d+) pages?", log)
    page_str = ", {} pages".format(pages.group(1)) if pages else ""

    if errors or latex_err:
        print("\nRESULT: PROBLEMS (see above)")
        return 2
    if undefined or float_too_large:
        print("\nRESULT: COMPILE OK{} — review undefined refs / oversized floats above".format(page_str))
        return 2
    print("\nRESULT: COMPILE OK{}".format(page_str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
