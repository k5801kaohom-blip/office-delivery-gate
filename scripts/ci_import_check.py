#!/usr/bin/env python3
"""Import every script a skill ships, and report honestly what happened.

A script can run and print usage while failing at import time for every consumer, so
`--help` is not a substitute for importing it. This imports each shipped script for real
and separates two outcomes that must not look alike:

- a missing third-party dependency  → the environment is incomplete
- any other error                    → the script is broken

Both fail. The distinction is in the message, because the fix is different: install the
declared dependencies, versus fix the code.

Usage:
    python3 ci_import_check.py --skill-dir DIR [--json OUT]

Exit codes:
    0  every shipped script imported
    1  at least one script could not be imported
    2  bad input
"""

import argparse
import importlib.util
import json
import sys
import traceback
from pathlib import Path


def import_script(path: Path) -> tuple[bool, str, str]:
    """Return (ok, kind, message). kind is 'ok', 'missing_dependency' or 'broken'."""
    spec = importlib.util.spec_from_file_location(f"_ci_check_{path.stem}", path)
    if spec is None or spec.loader is None:
        return False, "broken", "could not build an import spec"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return True, "ok", ""
    except ModuleNotFoundError as exc:
        return False, "missing_dependency", f"{exc.name} is not installed"
    except SyntaxError as exc:
        return False, "broken", f"syntax error: {exc}"
    except Exception:  # noqa: BLE001 - any import-time failure is a failure
        last = traceback.format_exc().strip().splitlines()[-1]
        return False, "broken", last


def main() -> int:
    ap = argparse.ArgumentParser(description="Import every script a skill ships.")
    ap.add_argument("--skill-dir", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    skill_dir = args.skill_dir.resolve()
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        print(f"note: {skill_dir.name} ships no scripts/ directory; nothing to import")
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(
                {"skill": skill_dir.name, "checked": 0, "results": [], "verdict": "NOTHING_TO_CHECK"},
                ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    scripts = sorted(p for p in scripts_dir.rglob("*.py") if p.is_file())
    if not scripts:
        print(f"note: {scripts_dir} contains no Python files; nothing to import")
        return 0

    results = []
    failures = 0
    missing_deps = set()

    for path in scripts:
        ok, kind, message = import_script(path)
        rel = str(path.relative_to(skill_dir))
        results.append({"script": rel, "ok": ok, "kind": kind, "message": message})
        if ok:
            print(f"  ok    {rel}")
        else:
            failures += 1
            if kind == "missing_dependency":
                missing_deps.add(message.split(" is not installed")[0])
                print(f"  FAIL  {rel}")
                print(f"          missing dependency: {message}")
            else:
                print(f"  FAIL  {rel}")
                print(f"          {message}")

    print()
    if failures:
        print(f"{failures} of {len(scripts)} shipped script(s) could not be imported")
        if missing_deps:
            print()
            print("Missing third-party dependencies: " + ", ".join(sorted(missing_deps)))
            print("Declare them so CI can install them, for example in requirements.txt:")
            for dep in sorted(missing_deps):
                print(f"  {dep}")
            print()
            print("An uninstalled dependency is not a pass. A skill whose scripts cannot be")
            print("imported in a clean environment is unusable by anyone who clones it.")
    else:
        print(f"all {len(scripts)} shipped script(s) imported")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "skill": skill_dir.name,
            "checked": len(scripts),
            "failed": failures,
            "missing_dependencies": sorted(missing_deps),
            "results": results,
            "verdict": "IMPORTS_OK" if failures == 0 else "IMPORTS_FAILED",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report: {args.json}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())