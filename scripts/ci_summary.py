#!/usr/bin/env python3
"""Render verification reports as a GitHub Actions job summary.

Understands both report shapes the pipeline produces, and detects which one it was handed
rather than requiring the caller to say so:

- a repository verification report (from verify_skill_repo.sh --json)
- a skill contract report (from check_skill_contract.py --json)

A missing report is reported as missing, not as success. A stage whose report never got
written did not pass; treating an absent file as green is how a pipeline reports health it
never measured.

Usage:
    python3 ci_summary.py REPORT [REPORT ...]        # print markdown
    python3 ci_summary.py --help
"""

import argparse
import json
import sys
from pathlib import Path

ICON = {"PASS": "pass", "FAIL": "**FAIL**", "SKIP": "skip"}


def detect_kind(doc: dict) -> str:
    if "checks" in doc:
        return "verify"
    if "stages" in doc:
        return "negative_control"
    # The import report also carries a `verdict`, so it must be recognised before the
    # contract report. Both have a verdict; only one has documented_resources.
    if "results" in doc and "missing_dependencies" in doc:
        return "imports"
    if "documented_resources" in doc or "verdict" in doc:
        return "contract"
    return "unknown"


def render_verify(doc: dict) -> list[str]:
    out = [
        f"**Verdict: {doc.get('verdict')}** — "
        f"{doc.get('passed', 0)} passed, {doc.get('failed', 0)} failed, "
        f"{doc.get('skipped', 0)} skipped",
        "",
        "| Status | Check | Detail |",
        "| --- | --- | --- |",
    ]
    for c in doc.get("checks", []):
        status = c.get("status", "")
        out.append(f"| {ICON.get(status, status)} | {c.get('check', '')} | {c.get('detail', '')} |")

    skipped = [c for c in doc.get("checks", []) if c.get("status") == "SKIP"]
    if skipped:
        out += [
            "",
            f"> {len(skipped)} stage(s) skipped. A skipped stage is not a passed stage — it is "
            "an unmeasured one.",
        ]
    return out


def render_contract(doc: dict) -> list[str]:
    problems = doc.get("problems", [])
    out = [
        f"**Verdict: {doc.get('verdict')}** — "
        f"{doc.get('checked', 0)} documented resources checked, {len(problems)} problem(s)",
        "",
    ]
    if problems:
        out += ["| Problem |", "| --- |"]
        for p in problems:
            out.append(f"| {p} |")
    else:
        out.append("Every resource SKILL.md names exists, compiles, and is executable.")
    return out


def render_negative_control(doc: dict) -> list[str]:
    out = [
        f"**Verdict: {doc.get('verdict')}** — "
        f"{doc.get('passed', 0)}/{doc.get('passed', 0) + doc.get('failed', 0)} stages passed",
        "",
        "| Status | Stage | Detail |",
        "| --- | --- | --- |",
    ]
    for s in doc.get("stages", []):
        out.append(f"| {'pass' if s.get('ok') else '**FAIL**'} | "
                   f"{s.get('stage', '')} | {s.get('detail', '')} |")
    return out


def render_imports(doc: dict) -> list[str]:
    results = doc.get("results", [])
    failed = [r for r in results if not r.get("ok")]
    out = [
        f"**Verdict: {doc.get('verdict')}** — "
        f"{doc.get('checked', 0)} shipped script(s) checked, {len(failed)} failed",
        "",
    ]
    deps = doc.get("missing_dependencies") or []
    if deps:
        out += [
            "Missing third-party dependencies: " + ", ".join(f"`{d}`" for d in deps),
            "",
            "> An uninstalled dependency is not a pass. Declare it in `requirements.txt` "
            "so CI can install it before checking imports.",
            "",
        ]
    if failed:
        out += ["| Script | Problem |", "| --- | --- |"]
        for r in failed:
            out.append(f"| `{r.get('script', '')}` | {r.get('message', '')} |")
    else:
        out.append("Every shipped script imports in a clean environment.")
    return out


RENDERERS = {
    "verify": render_verify,
    "contract": render_contract,
    "negative_control": render_negative_control,
    "imports": render_imports,
}


def render(path: Path) -> list[str]:
    lines = [f"### {path.name}", ""]
    if not path.is_file():
        return lines + [f"_report not produced: `{path}`_", "",
                        "> A stage whose report was never written did not pass.", ""]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return lines + [f"_report unreadable: {exc}_", ""]

    kind = detect_kind(doc)
    fn = RENDERERS.get(kind)
    if fn is None:
        return lines + ["_unrecognised report shape_", ""]
    return lines + fn(doc) + [""]


def main() -> int:
    ap = argparse.ArgumentParser(description="Render verification reports as job summary markdown.")
    ap.add_argument("reports", nargs="*", type=Path, help="report JSON files")
    ap.add_argument("--require", action="store_true",
                    help="exit non-zero if any report is missing or unreadable")
    args = ap.parse_args()

    if not args.reports:
        print("usage: ci_summary.py REPORT [REPORT ...]", file=sys.stderr)
        return 2

    missing = False
    for path in args.reports:
        if not path.is_file():
            missing = True
        for line in render(path):
            print(line)

    if missing and args.require:
        print("one or more reports were not produced", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
