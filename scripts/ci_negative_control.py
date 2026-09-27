#!/usr/bin/env python3
"""Prove the contract checker actually rejects broken skills.

A checker that always passes is worse than no checker: it manufactures confidence while
detecting nothing. A green contract stage is only evidence if the checker can fail, and the
only way to know it can fail is to make it fail on purpose.

This runs the checker against copies of a skill that are broken in each way the checker
claims to detect, and fails the build if any fault slips through. It also re-runs the
baseline afterwards, so a fault that leaks into the working tree cannot pass unnoticed.

Usage:
    python3 ci_negative_control.py --skill DIR [--checker PATH] [--json OUT]

Exit codes:
    0  the checker accepted a valid skill and rejected every injected fault
    1  a fault slipped through, or a valid skill was rejected
    2  bad input
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Each entry: (name, description, mutator). The mutator receives a private copy of the
# skill and must break exactly one thing the checker claims to detect.
FAULTS = [
    (
        "documented_but_missing",
        "SKILL.md names a resource that does not exist",
        lambda root: append_to_skill_md(
            root, "\n- `scripts/does_not_exist.py` \u2014 injected fault\n"
        ),
    ),
    (
        "not_executable",
        "a documented script is not executable",
        lambda root: clear_exec_bit(root),
    ),
    (
        "does_not_compile",
        "a documented script has a syntax error",
        lambda root: break_syntax(root),
    ),
]


def append_to_skill_md(root: Path, text: str) -> None:
    md = root / "SKILL.md"
    md.write_text(md.read_text(encoding="utf-8") + text, encoding="utf-8")


def first_documented_script(root: Path) -> Path | None:
    md = (root / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"scripts/[A-Za-z0-9_.-]+\.py", md)
    if not m:
        return None
    p = root / m.group(0)
    return p if p.is_file() else None


def clear_exec_bit(root: Path) -> None:
    target = first_documented_script(root)
    if target is None:
        raise RuntimeError("no documented script found to chmod")
    target.chmod(target.stat().st_mode & ~0o111)


def break_syntax(root: Path) -> None:
    target = first_documented_script(root)
    if target is None:
        raise RuntimeError("no documented script found to break")
    with target.open("a", encoding="utf-8") as fh:
        fh.write("\ndef broken(:\n")


def find_checker(skill: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    for cand in (skill / "scripts/check_skill_contract.py",
                 skill.parent / "scripts/check_skill_contract.py"):
        if cand.is_file():
            return cand
    return None


def run_checker(checker: Path, skill: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(checker), "--skill", str(skill)],
        capture_output=True, text=True, timeout=120,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def verdict_of(output: str) -> str:
    m = re.search(r"VERDICT:\s*(\S+)", output)
    return m.group(1) if m else "(no verdict)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Prove the contract checker rejects broken skills.")
    ap.add_argument("--skill", type=Path, required=True)
    ap.add_argument("--checker", default=None)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--keep", action="store_true", help="keep the injected copies for inspection")
    args = ap.parse_args()

    skill = args.skill.resolve()
    if not (skill / "SKILL.md").is_file():
        print(f"error: no SKILL.md in {skill}", file=sys.stderr)
        return 2

    checker = find_checker(skill, args.checker)
    if checker is None:
        print("error: no check_skill_contract.py found; pass --checker", file=sys.stderr)
        return 2

    print(f"skill   : {skill.name}")
    print(f"checker : {checker}")
    print()

    stages = []
    failed = 0
    tmpdir = Path(tempfile.mkdtemp(prefix="negctl-"))

    def record(name, ok, detail):
        nonlocal failed
        if not ok:
            failed += 1
        stages.append({"stage": name, "ok": ok, "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<28} {detail}")

    try:
        # Stage 1: the checker must accept the real skill. A checker that rejects
        # everything is as useless as one that accepts everything.
        rc, out = run_checker(checker, skill)
        record("baseline_accepts_valid", rc == 0,
               f"exit={rc} {verdict_of(out)}")

        # Stages 2..n: each injected fault must be rejected.
        for name, description, mutate in FAULTS:
            work = tmpdir / name
            shutil.copytree(skill, work,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
            try:
                mutate(work)
            except RuntimeError as exc:
                record(f"rejects_{name}", False, f"could not inject: {exc}")
                continue
            rc, out = run_checker(checker, work)
            record(f"rejects_{name}", rc != 0,
                   f"exit={rc} {verdict_of(out)} \u2014 {description}")
            if not args.keep:
                shutil.rmtree(work, ignore_errors=True)

        # Final stage: the real skill must still be accepted. Catches a mutator that
        # edited the original instead of the copy.
        rc, out = run_checker(checker, skill)
        record("baseline_unchanged_after", rc == 0,
               f"exit={rc} {verdict_of(out)}")
    finally:
        if not args.keep:
            shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    ok_count = sum(1 for s in stages if s["ok"])
    print(f"negative control: {ok_count}/{len(stages)} stages passed")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "skill": skill.name,
            "checker": str(checker),
            "stages": stages,
            "passed": ok_count,
            "failed": failed,
            "verdict": "CHECKER_PROVEN" if failed == 0 else "CHECKER_UNPROVEN",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report: {args.json}")

    if failed:
        print()
        print("The checker did not reject a fault it claims to detect, so a green contract")
        print("stage proves nothing. Fix the checker before trusting the pipeline.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())