#!/usr/bin/env python3
"""Pre-delivery gate for Office (OOXML) files.

Runs the full four-step procedure on every file: validate, repair if needed,
re-validate, then confirm the repair did not destroy content.

Exit codes
    0   every file is safe to deliver
    1   at least one file is blocked (repairable defects passed over, or repair failed)
    2   usage or environment error
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# --------------------------------------------------------------------- helpers

_CANDIDATES = [
    Path(os.environ["OOXML_SKILL_DIR"]) if os.environ.get("OOXML_SKILL_DIR") else None,
    Path("/home/ubuntu/skills/ooxml-integrity-check/scripts"),
    Path(__file__).resolve().parent.parent / "ooxml-integrity-check" / "scripts",
    Path(__file__).resolve().parent.parent.parent / "ooxml-integrity-check" / "scripts",
]

_OFFICE_SUFFIXES = {".pptx", ".docx", ".xlsx", ".pptm", ".docm", ".xlsm"}


def find_helper(name: str) -> Path:
    for base in _CANDIDATES:
        if not base:
            continue
        candidate = Path(base) / name
        if candidate.is_file():
            return candidate
    raise SystemExit(
        f"[gate] cannot locate {name}.\n"
        f"        Install the ooxml-integrity-check skill alongside this one, or point\n"
        f"        OOXML_SKILL_DIR at its scripts/ directory."
    )


def run_validator(script: Path, target: Path, report_path: Path | None) -> tuple[int, str, dict]:
    cmd = [sys.executable, str(script), str(target), "--quiet"]
    if report_path is not None:
        cmd += ["--json", str(report_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    data: dict = {}
    if report_path is not None and report_path.is_file():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    return proc.returncode, (proc.stdout + proc.stderr).strip(), data


def run_repair(script: Path, target: Path, out_path: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(script), str(target), "-o", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


# ------------------------------------------------------------- content witness

def fingerprint(path: Path) -> dict:
    """Describe what the file contains, so a repair cannot silently drop content."""
    fp: dict = {"readable": False}
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            fp["readable"] = True
            fp["parts"] = len(names)
            fp["slides"] = len([n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)])
            fp["sheets"] = len([n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)])
            fp["media"] = len([n for n in names if n.startswith(("ppt/media/", "word/media/", "xl/media/"))])

            text_chars = 0
            text_runs = 0
            for name in names:
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name) or name in (
                    "word/document.xml",
                    "xl/sharedStrings.xml",
                ):
                    blob = z.read(name).decode("utf-8", "ignore")
                    runs = re.findall(r"<(?:a|w):t\b[^>]*>(.*?)</(?:a|w):t>", blob, flags=re.S)
                    text_runs += len(runs)
                    text_chars += sum(len(r) for r in runs)
            fp["text_runs"] = text_runs
            fp["text_chars"] = text_chars
    except (zipfile.BadZipFile, OSError):
        pass
    return fp


# ------------------------------------------------------------------ the gate

def gate(path: Path, repair_script: Path, workdir: Path, auto_repair: bool) -> dict:
    validate_script = find_helper("validate_ooxml.py")

    entry: dict = {"input": str(path), "kind": path.suffix.lstrip("."), "action": "none"}

    if not path.is_file():
        entry.update(verdict="BLOCKED", note="file does not exist")
        return entry

    report = workdir / f"{path.stem}.initial.json"
    code, output, initial = run_validator(validate_script, path, report)
    entry["initial"] = {
        "problem_count": initial.get("problem_count", 0),
        "problems": {k: v for k, v in (initial.get("problems") or {}).items() if v},
    }
    entry["initial_output"] = output
    entry["content_before"] = fingerprint(path)

    if code == 0:
        entry["final"] = entry["initial"]
        entry["verdict"] = "SAFE"
        return entry

    # The file fails. Repair is only acceptable when the gate can prove the result
    # is both valid AND still contains the same content.
    if not auto_repair:
        entry.update(
            verdict="BLOCKED",
            note=f"{entry['initial']['problem_count']} problem(s); re-run with --repair to attempt a fix",
        )
        return entry

    repaired = workdir / f"{path.stem}.repaired{path.suffix}"
    rcode, routput = run_repair(repair_script, path, repaired)
    entry["action"] = "repaired"
    entry["repair_output"] = routput

    if not repaired.is_file():
        entry.update(verdict="BLOCKED", note="repair produced no output file; fix the source instead")
        return entry

    report2 = workdir / f"{path.stem}.final.json"
    code2, output2, final = run_validator(validate_script, repaired, report2)
    entry["repaired_path"] = str(repaired)
    entry["final"] = {
        "problem_count": final.get("problem_count", 0),
        "problems": {k: v for k, v in (final.get("problems") or {}).items() if v},
    }
    entry["final_output"] = output2
    entry["content_after"] = fingerprint(repaired)

    before, after = entry["content_before"], entry["content_after"]
    if not after.get("readable"):
        entry.update(verdict="BLOCKED", note="repaired file is not readable as an Office package")
        return entry

    for key in ("slides", "sheets", "media", "text_runs"):
        if before.get(key, 0) != after.get(key, 0):
            entry.update(
                verdict="BLOCKED",
                note=f"repair changed {key}: {before.get(key, 0)} -> {after.get(key, 0)}",
            )
            return entry

    if code2 != 0:
        entry.update(
            verdict="BLOCKED",
            note=f"{final.get('problem_count', 0)} problem(s) need a source-level fix; not mechanical",
        )
        return entry

    entry["verdict"] = "SAFE"
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-delivery gate for Office files.")
    ap.add_argument("files", nargs="+", help="Office files to clear for delivery")
    ap.add_argument("--repair", action="store_true",
                    help="attempt automatic repair; the result must pass and keep its content")
    ap.add_argument("--workdir", default=None,
                    help="directory for repaired files and reports (default: ./delivery_gate)")
    ap.add_argument("--json", dest="json_out", default=None, help="write a consolidated report here")
    args = ap.parse_args()

    try:
        repair_script = find_helper("repair_ooxml.py")
        find_helper("validate_ooxml.py")
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2

    workdir = Path(args.workdir or "delivery_gate")
    workdir.mkdir(parents=True, exist_ok=True)

    targets = []
    for raw in args.files:
        p = Path(raw)
        if p.is_dir():
            targets += sorted(f for f in p.iterdir() if f.suffix.lower() in _OFFICE_SUFFIXES)
        else:
            targets.append(p)

    if not targets:
        print("[gate] no Office files found to check", file=sys.stderr)
        return 2

    print(f"[gate] checking {len(targets)} file(s)\n")
    results = [gate(p, repair_script, workdir, args.repair) for p in targets]

    blocked = [r for r in results if r.get("verdict") != "SAFE"]
    for r in results:
        name = Path(r["input"]).name
        if r["verdict"] == "SAFE":
            n = r["initial"]["problem_count"]
            if n:
                print(f"  SAFE     {name}   ({n} problem(s) repaired, content preserved)")
            else:
                print(f"  SAFE     {name}   (all checks passed)")
        else:
            print(f"  BLOCKED  {name}   {r.get('note', '')}")
            for check, items in (r.get("final") or r.get("initial", {})).get("problems", {}).items():
                for item in items[:3]:
                    print(f"             - {check}: {item}")

    print()
    if blocked:
        print(f"[gate] {len(blocked)} of {len(results)} file(s) must NOT be delivered yet.")
    else:
        print(f"[gate] all {len(results)} file(s) are safe to deliver.")

    if args.json_out:
        payload = {
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "verdict": "BLOCKED" if blocked else "SAFE",
            "checked": len(results),
            "blocked": len(blocked),
            "results": results,
        }
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[gate] report written to {args.json_out}")

    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())