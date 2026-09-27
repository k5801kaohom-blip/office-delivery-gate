#!/usr/bin/env python3
"""Check that a skill actually contains what its SKILL.md tells the agent to use.

SKILL.md is a promise: it names scripts, references, and templates the agent will try to
run. Nothing verifies that promise, so a skill can document a pipeline whose files were
never installed. This walks the documentation and checks each resource against the tree.

Usage:
    python check_skill_contract.py --skill DIR [--json OUT]

Exit codes:
    0  every referenced resource exists and is usable
    1  contract violations found
    2  bad input
"""

import argparse
import json
import re
import sys
from pathlib import Path

RESOURCE_DIRS = ("scripts", "references", "templates", "assets")
# scripts/foo.py, references/bar.md, templates/baz.json, and absolute skill paths
REL_PATTERN = re.compile(
    r"(?<![\w./-])((?:%s)/[A-Za-z0-9_.][A-Za-z0-9_./-]*\.[A-Za-z0-9]+)" % "|".join(RESOURCE_DIRS))
ABS_PATTERN = re.compile(
    r"(/home/ubuntu/skills/[^/\s`\"']+/(?:%s)/[A-Za-z0-9_.][A-Za-z0-9_./-]*)" % "|".join(RESOURCE_DIRS))
PLACEHOLDERS = ("TODO", "FIXME", "example.py", "example_template.txt",
                "api_reference.md", "[TODO")


def referenced(skill_dir: Path, text: str) -> set:
    """Collect resource paths named in the documentation, as skill-relative paths."""
    found = set()
    for m in REL_PATTERN.finditer(text):
        found.add(m.group(1))
    for m in ABS_PATTERN.finditer(text):
        p = Path(m.group(1))
        # only keep paths that point inside this skill
        try:
            found.add(str(p.relative_to(skill_dir)))
        except ValueError:
            continue
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="Check a skill's documentation against its files.")
    ap.add_argument("--skill", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    skill = args.skill
    if not (skill / "SKILL.md").is_file():
        print(f"error: no SKILL.md in {skill}", file=sys.stderr)
        return 2

    doc = (skill / "SKILL.md").read_text(encoding="utf-8")
    problems = []

    # 1. frontmatter
    if not doc.startswith("---"):
        problems.append("SKILL.md has no YAML frontmatter")
    else:
        fm = doc.split("---", 2)[1] if doc.count("---") >= 2 else ""
        for field in ("name:", "description:"):
            if field not in fm:
                problems.append(f"frontmatter is missing `{field}`")

    # 2. every documented resource must exist
    named = sorted(referenced(skill, doc))
    missing = [r for r in named if not (skill / r).is_file()]
    for r in missing:
        problems.append(f"documented but not present: {r}")

    # 3. documented scripts must compile, be non-empty, and be executable
    checked = 0
    for r in named:
        p = skill / r
        if r in missing:
            continue
        checked += 1
        if p.stat().st_size == 0:
            problems.append(f"empty file: {r}")
        if p.suffix == ".py":
            try:
                compile(p.read_text(encoding="utf-8"), str(p), "exec")
            except SyntaxError as exc:
                problems.append(f"{r} does not compile: {exc}")
            if not (p.stat().st_mode & 0o111):
                problems.append(f"{r} is not executable")

    # 4. leftover scaffolding
    for p in skill.rglob("*"):
        if not p.is_file() or p.name == "SKILL.md":
            continue
        if any(tok in str(p) for tok in PLACEHOLDERS):
            problems.append(f"leftover scaffold file: {p.relative_to(skill)}")
    for i, line in enumerate(doc.splitlines(), 1):
        # A skill may legitimately document the marker itself, so ignore lines that are
        # clearly explanatory (inside backticks) and only flag bare placeholders.
        stripped = line.replace("`", "")
        if "[TODO" in stripped and not stripped.lstrip().startswith(("-", "*", "|", "#")):
            problems.append(f"SKILL.md line {i} still contains a TODO placeholder")

    report = {
        "skill": str(skill),
        "documented_resources": named,
        "checked": checked,
        "problems": problems,
        "verdict": "CONTRACT_OK" if not problems else "CONTRACT_VIOLATED",
    }

    print(f"skill: {skill}")
    print(f"documented resources: {len(named)}  (checked {checked})")
    for r in named:
        mark = "MISSING" if r in missing else "ok"
        print(f"  [{mark:7}] {r}")
    print()
    if problems:
        print(f"PROBLEMS ({len(problems)}):")
        for p in problems:
            print(f"  - {p}")
    else:
        print("Every documented resource exists, compiles, and is executable.")
    print()
    print(f"VERDICT: {report['verdict']}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report: {args.json}")

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
