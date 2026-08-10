#!/usr/bin/env python3
"""Verify README's taxonomy table against the pattern files it indexes.

CONTRIBUTING tells contributors to check the README table before proposing a
pattern, so that table is load-bearing: if it under-reports a category, the next
contributor re-files an existing pattern under a new ID. It drifts silently
because adding a pattern to `patterns/X.md` and updating the row in `README.md`
are two edits and only one of them is where the work happens.

This checks three things:

    every category with a pattern file has a row, and vice versa
    each row's ID range matches the first and last pattern in its file
    the stated total matches the number of patterns actually documented

Run it before opening a PR:

    python3 rules/check_taxonomy.py

Exit status is 1 on any mismatch -- unlike the advisory reachability report, this
one is a gate. It compares two things in this repo and is never environment
dependent, so a failure is always a real inconsistency.
"""
from __future__ import annotations

import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# "## RG1 — Registry-Registered Symbol Reported Unreachable", "## MC1b — ..."
PATTERN_HEADING = re.compile(r"^## ([A-Z]{1,4})(\d+[a-z]?)\b", re.M)
# "| RG  | Reachability Gap | RG1–RG4 | ... |" -- en dash or hyphen.
TABLE_ROW = re.compile(r"^\| ([A-Z]{1,4})\s+\|[^|]+\|\s*([A-Za-z0-9]+)[–-]([A-Za-z0-9]+)\s*\|", re.M)
TOTAL = re.compile(r"\*\*Total: (\d+) documented patterns\*\*")


def documented() -> dict[str, list[str]]:
    """{category: [pattern ids, in file order]} across every patterns/*.md."""
    out: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted((ROOT / "patterns").glob("*.md")):
        for match in PATTERN_HEADING.finditer(path.read_text(encoding="utf-8")):
            out[match.group(1)].append(match.group(1) + match.group(2))
    return dict(out)


def main() -> int:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    patterns = documented()
    rows = {m.group(1): (m.group(2), m.group(3)) for m in TABLE_ROW.finditer(readme)}

    problems: list[str] = []

    for category in sorted(set(patterns) | set(rows)):
        ids = patterns.get(category)
        row = rows.get(category)
        if ids and not row:
            problems.append(f"{category}: has patterns/{category}-*.md but no row in the README table")
        elif row and not ids:
            problems.append(f"{category}: has a README row but no patterns documented under it")
        elif (ids[0], ids[-1]) != row:
            problems.append(
                f"{category}: table says {row[0]}–{row[1]}, files document {ids[0]}–{ids[-1]}")

    total_match = TOTAL.search(readme)
    if total_match is None:
        problems.append("README has no '**Total: N documented patterns**' line")
    else:
        stated, counted = int(total_match.group(1)), sum(len(v) for v in patterns.values())
        if stated != counted:
            problems.append(f"total: README states {stated}, files document {counted}")

    if problems:
        print("README taxonomy is out of sync with patterns/:\n")
        for p in problems:
            print(f"  {p}")
        print(f"\n{len(problems)} problem(s).")
        return 1

    print(f"taxonomy OK: {len(rows)} categories, "
          f"{sum(len(v) for v in patterns.values())} patterns, table matches files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
