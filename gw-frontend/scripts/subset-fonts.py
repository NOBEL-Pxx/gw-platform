#!/usr/bin/env python3
"""R6.44: Generate font subsets from src/ chars (per-page + verify mode).

Reads app source, computes required chars per page, generates woff2 subsets.

Usage:
    python scripts/subset-fonts.py              # regenerate all
    python scripts/subset-fonts.py --verify     # CI gate: fail if stale
    python scripts/subset-fonts.py --pages-only # only per-page subsets

Subsets generated:
    inter-latin.woff2           - basic Latin (always)
    jetbrains-mono-latin.woff2  - basic Latin (always)
    inter-landing.woff2         - chars used in src/pages/landing/**
    inter-home.woff2            - chars used in src/pages/home/**
    inter-index.woff2           - chars used in src/pages/index/**
    inter-settings.woff2        - chars used in src/pages/settings/**
    inter-assistant.woff2       - chars used in src/pages/assistant/**

CI mode (--verify):
    - Regenerates subsets in a temp dir
    - Diffs against committed public/fonts/*.woff2
    - Exits non-zero (1) if any subset changed
    - Exits 0 if everything matches
"""
import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
FONTS = ROOT / "public" / "fonts"
FONTS.mkdir(exist_ok=True)

PER_PAGE_DIRS = ["landing", "home", "index", "settings", "assistant"]


def collect_chars(paths):
    """Collect unique chars from given source paths."""
    chars = set()
    for ext in ("tsx", "ts", "css", "html"):
        for f in paths:
            if f.is_file():
                try:
                    if f.suffix == "." + ext:
                        chars.update(f.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
            else:
                for sub in f.rglob("*." + ext):
                    try:
                        chars.update(sub.read_text(encoding="utf-8", errors="ignore"))
                    except Exception:
                        pass
    return chars


def get_basic_chars():
    """Always include basic printable ASCII + Latin-1 + CJK punctuation."""
    basic = set(' !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyz{|}~')
    # Latin-1 supplement + general punctuation + CJK punctuation
    extra = '€£¥©®™°±×÷¼½¾§¶†‡•…‰′″¤¦¨ª«¯­¸¹º¿¡¢£¤¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º»¼½¾¿'
    basic |= set(extra)
    cjk = '，。！？；：（）【】《》""''「」、…—·'
    basic |= set(cjk)
    return basic


def subset_one(src_file, out_file, unicodes, label):
    """Run pyftsubset. Returns True on success."""
    if not src_file.exists():
        print("[subset-fonts] SKIP " + label + ": source missing (" + src_file.name + ")")
        return False
    out_file.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        sys.executable, "-m", "fontTools.subset", str(src_file),
        "--output-file=" + str(out_file),
        "--unicodes=" + unicodes,
        "--flavor=woff2",
        "--no-hinting",
        "--desubroutinize",
    ], capture_output=True, text=True)
    if result.returncode == 0 and out_file.exists():
        size_kb = out_file.stat().st_size / 1024
        print("[subset-fonts] " + label + ": " + str(round(size_kb, 1)) + " KB (" + out_file.name + ")")
        return True
    else:
        print("[subset-fonts] ERR " + label + ": " + result.stderr[:200])
        return False


def md5(p):
    """File md5 for staleness check."""
    return hashlib.md5(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Per-page font subset generator")
    parser.add_argument("--verify", action="store_true",
                        help="CI gate: exit 1 if subsets are stale")
    parser.add_argument("--pages-only", action="store_true",
                        help="Only generate per-page subsets")
    args = parser.parse_args()

    basic_chars = get_basic_chars()
    all_chars = collect_chars([SRC]) | basic_chars
    print("[subset-fonts] global: " + str(len(all_chars)) + " unique chars")

    page_chars = {}
    for page in PER_PAGE_DIRS:
        page_path = SRC / "pages" / page
        if not page_path.exists():
            print("[subset-fonts] WARN page " + page + " not found, skip")
            continue
        chars = collect_chars([page_path]) | basic_chars
        page_chars[page] = chars
        print("[subset-fonts] page " + page + ": " + str(len(chars)) + " chars")

    (FONTS / "subset-chars.txt").write_text("".join(sorted(all_chars)), encoding="utf-8")

    inter_src = FONTS / "inter-var.woff2"
    mono_src = FONTS / "jetbrains-mono-regular.woff2"
    latin_unicodes = "U+0020-007F, U+00A0-00FF"

    work_dir = FONTS
    if args.verify:
        work_dir = Path(tempfile.mkdtemp(prefix="font_subset_verify_"))
        print("[subset-fonts] --verify: working in " + str(work_dir))

    if not args.pages_only:
        subset_one(inter_src, work_dir / "inter-latin.woff2", latin_unicodes, "inter latin")
        subset_one(mono_src, work_dir / "jetbrains-mono-latin.woff2", latin_unicodes, "jetbrains latin")

    for page, chars in page_chars.items():
        if not chars:
            continue
        codepoints = sorted({f"U+{ord(c):04X}" for c in chars if ord(c) < 0xFFFF})
        unicodes = ",".join(codepoints[:500])
        if not unicodes:
            continue
        subset_one(inter_src, work_dir / ("inter-" + page + ".woff2"), unicodes, "inter " + page)

    # Files THIS script manages (others are left alone: sources, R6.40 leftovers)
    managed_files = []
    if not args.pages_only:
        managed_files.append("inter-latin.woff2")
        managed_files.append("jetbrains-mono-latin.woff2")
    for page in page_chars:
        managed_files.append("inter-" + page + ".woff2")

    if args.verify:
        stale = []
        for name in managed_files:
            committed = FONTS / name
            regenerated = work_dir / name
            if not committed.exists():
                stale.append(name + ": missing from committed fonts/")
                continue
            if not regenerated.exists():
                stale.append(name + ": failed to generate")
                continue
            if md5(committed) != md5(regenerated):
                stale.append(name + ": content drift")
        if stale:
            print("[subset-fonts] STALE SUBSETS DETECTED:")
            for s in stale:
                print("  - " + s)
            print("[subset-fonts] Run: python scripts/subset-fonts.py && git add public/fonts/")
            return 1
        print("[subset-fonts] --verify: all " + str(len(managed_files)) + " managed subsets up to date")
        return 0

    print("[subset-fonts] Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
