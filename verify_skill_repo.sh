#!/usr/bin/env bash
# Verify this skill repository is fully in sync with its remote, and that a fresh clone
# reproduces a working skill.
#
# The skill name and repository slug are auto-detected, so nothing has to be edited after
# scaffolding. This script is written to run unchanged on a developer machine, in a sandbox,
# and in CI:
#   - no absolute paths
#   - no dependency on a separately installed skill
#   - no network beyond `git fetch` on the default path
#   - credentials only needed behind --api
#
# Usage:
#   ./verify_skill_repo.sh                 # full check against origin/main
#   ./verify_skill_repo.sh --api           # also verify the served content via gh
#   ./verify_skill_repo.sh --offline       # local integrity only, no fetch
#   ./verify_skill_repo.sh --skip-clone    # skip the fresh-clone stage
#   ./verify_skill_repo.sh --json OUT      # write a machine-readable summary
#
# Exit codes:
#   0  fully in sync and reproducible
#   1  problems found
#   2  bad input / missing prerequisite

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

USE_API=0
OFFLINE=0
SKIP_CLONE=0
JSON_OUT=""
FAIL=0
declare -a RESULTS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --api)        USE_API=1 ;;
    --offline)    OFFLINE=1 ;;
    --skip-clone) SKIP_CLONE=1 ;;
    --json)       JSON_OUT="${2:-}"; shift ;;
    -h|--help)    sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

record() {  # status, name, detail
  RESULTS+=("$1|$2|$3")
  [ "$1" = "FAIL" ] && FAIL=1
  printf '  [%-4s] %-46s %s\n' "$1" "$2" "$3"
}
need() { command -v "$1" >/dev/null 2>&1; }

for tool in git python3; do
  need "$tool" || { echo "error: required tool not found: $tool" >&2; exit 2; }
done
if [ "$USE_API" -eq 1 ] && ! need gh; then
  echo "error: --api requires the gh CLI" >&2
  exit 2
fi

# ------------------------------------------------------------------ auto-detection
SKILL_MD="$(find "$ROOT" -maxdepth 2 -name SKILL.md -not -path '*/.git/*' 2>/dev/null | head -1)"
if [ -z "$SKILL_MD" ]; then
  echo "error: no SKILL.md found under $ROOT" >&2
  exit 2
fi
SKILL_NAME="$(basename "$(dirname "$SKILL_MD")")"
SKILL_DIR="$ROOT/$SKILL_NAME"

SLUG="$(git config --get remote.origin.url 2>/dev/null \
        | sed -e 's#^git@github.com:#https://github.com/#' -e 's#\.git$##' \
        | sed -e 's#^https://github.com/##')"
[ -z "$SLUG" ] && SLUG="unknown/unknown"

# Clone from the actual remote URL rather than assuming github.com, so this works
# against an internal git server and can be tested end to end without network access.
CLONE_URL="$(git config --get remote.origin.url 2>/dev/null || echo '')"

echo "skill : $SKILL_NAME"
echo "repo  : $SLUG"
echo

# ---------------------------------------------------------------- 1. commit sync
echo "######## 1. commit sync ########"
if [ "$OFFLINE" -eq 1 ]; then
  record SKIP "commit sync" "offline mode"
else
  if git fetch -q origin 2>/dev/null; then
    record PASS "fetch origin" "ok"
  else
    record FAIL "fetch origin" "could not reach the remote"
  fi
fi

LH="$(git rev-parse HEAD 2>/dev/null || echo '')"
RH="$(git rev-parse origin/main 2>/dev/null || echo '')"
AB="$(git rev-list --left-right --count HEAD...origin/main 2>/dev/null || echo 'unknown')"
DIRTY="$(git status --porcelain | wc -l | tr -d ' ')"
echo "  local  HEAD : $LH"
echo "  remote main : $RH"
echo "  ahead/behind: $AB"
echo "  dirty files : $DIRTY"

if [ "$OFFLINE" -eq 0 ]; then
  if [ -n "$LH" ] && [ "$LH" = "$RH" ]; then
    record PASS "commits in sync" "$(git rev-parse --short HEAD)"
  else
    record FAIL "commits in sync" "HEAD != origin/main"
  fi
fi
if [ "$DIRTY" -eq 0 ]; then
  record PASS "working tree clean" "0 modified files"
else
  record FAIL "working tree clean" "$DIRTY modified file(s)"
fi

# ------------------------------------------------- 2. documented-resource contract
echo
echo "######## 2. skill contract ########"
# The checker may live in the skill payload (a skill that ships it as one of its own
# scripts) or at the repository root (repository tooling). Accept either.
CONTRACT=""
for cand in "$SKILL_DIR/scripts/check_skill_contract.py" "$ROOT/scripts/check_skill_contract.py"; do
  [ -f "$cand" ] && CONTRACT="$cand" && break
done

if [ ! -f "$SKILL_DIR/SKILL.md" ]; then
  record FAIL "skill contract" "no $SKILL_NAME/SKILL.md"
elif [ -n "$CONTRACT" ]; then
  OUT="$(python3 "$CONTRACT" --skill "$SKILL_DIR" 2>&1)"
  if [ $? -eq 0 ]; then
    record PASS "skill contract" "$(printf '%s\n' "$OUT" | grep -c '^  \[') documented resources"
  else
    record FAIL "skill contract" "CONTRACT_VIOLATED"
    printf '%s\n' "$OUT" | sed -n '/PROBLEMS/,/^$/p' | sed 's/^/      /'
  fi
else
  record SKIP "skill contract" "no checker shipped"
fi

# --------------------------------------------- 3. structural validation (inlined)
echo
echo "######## 3. skill structure ########"
STRUCT_OUT="$(python3 - "$SKILL_DIR" "$SKILL_NAME" <<'PY' 2>&1
import re, sys
from pathlib import Path

skill = Path(sys.argv[1]); name = sys.argv[2]
doc = skill / "SKILL.md"
if not doc.is_file():
    print("FAIL no SKILL.md"); raise SystemExit(1)
text = doc.read_text(encoding="utf-8")
problems = []

if not text.startswith("---"):
    problems.append("missing YAML frontmatter")
else:
    parts = text.split("---", 2)
    fm = parts[1] if len(parts) >= 3 else ""
    if "name:" not in fm:
        problems.append("frontmatter missing name:")
    elif not re.search(r"^name:\s*%s\s*$" % re.escape(name), fm, re.M):
        problems.append("frontmatter name does not match the directory name")
    if "description:" not in fm:
        problems.append("frontmatter missing description:")
    elif "[TODO" in fm:
        problems.append("frontmatter description still contains a TODO placeholder")

lines = len(text.splitlines())
if lines > 500:
    problems.append(f"SKILL.md is {lines} lines (keep under 500)")

for p in skill.rglob("*"):
    if p.is_file() and p.name in ("example.py", "example_template.txt", "api_reference.md"):
        problems.append(f"leftover scaffold: {p.relative_to(skill)}")

for f in sorted(skill.rglob("*.py")):
    try:
        compile(f.read_text(encoding="utf-8"), str(f), "exec")
    except SyntaxError as exc:
        problems.append(f"{f.relative_to(skill)} does not compile: {exc}")

if problems:
    print("FAIL")
    for p in problems:
        print(f"  - {p}")
    raise SystemExit(1)
print(f"OK {lines} lines, frontmatter valid, all python compiles")
PY
)"
if [ $? -eq 0 ]; then
  record PASS "skill structure" "${STRUCT_OUT#OK }"
else
  record FAIL "skill structure" "validation failed"
  printf '%s\n' "$STRUCT_OUT" | sed 's/^/      /'
fi

# ------------------------------------------------------- 4. content equality
# Proves the remote carries the same bytes, not merely the same commit id.
echo
echo "######## 4. content equality with origin/main ########"
if [ "$OFFLINE" -eq 1 ]; then
  record SKIP "content equality" "offline mode"
else
  DIFFS=0; COUNT=0
  while IFS= read -r f; do
    COUNT=$((COUNT + 1))
    if ! git diff --quiet origin/main -- "$f" 2>/dev/null; then
      record FAIL "identical: $f" "differs from origin/main"
      DIFFS=$((DIFFS + 1))
    fi
  done < <(git ls-tree -r --name-only origin/main 2>/dev/null)
  [ "$DIFFS" -eq 0 ] && record PASS "content equality" "$COUNT files byte-identical"
fi

# --------------------------------------------------- 5. payload hygiene
# Repository furniture must not end up inside the installed skill directory.
echo
echo "######## 5. payload hygiene ########"
LEAKED=0
for f in .gitignore LICENSE README.md; do
  if [ -e "$SKILL_DIR/$f" ]; then
    record FAIL "payload clean: $f" "should live at the repository root, not in $SKILL_NAME/"
    LEAKED=1
  fi
done
[ "$LEAKED" -eq 0 ] && record PASS "payload clean" "no repository files inside $SKILL_NAME/"

# ------------------------------------------------------ 6. API surface (opt-in)
GH_SLUG=""
case "$SLUG" in
  */*) GH_SLUG="$SLUG" ;;
esac
if [ "$USE_API" -eq 1 ] && [ -n "$GH_SLUG" ]; then
  echo
  echo "######## 6. GitHub API surface ########"
  if gh api "repos/$GH_SLUG/contents/$SKILL_NAME/SKILL.md" --jq '.content' 2>/dev/null \
       | base64 -d | cmp -s - "$SKILL_DIR/SKILL.md"; then
    record PASS "API serves identical SKILL.md" "via gh api"
  else
    record FAIL "API serves identical SKILL.md" "unexpected content"
  fi
fi

# ---------------------------------------------------- 7. clone reproducibility
echo
echo "######## 7. fresh clone reproduces a working skill ########"
if [ "$SKIP_CLONE" -eq 1 ]; then
  record SKIP "fresh clone" "skipped by request"
elif [ -z "$CLONE_URL" ]; then
  record SKIP "fresh clone" "no remote configured"
else
  WORKDIR="$(mktemp -d)"
  if git clone -q "$CLONE_URL" "$WORKDIR/clone" 2>/dev/null; then
    # A clone can succeed while checking out nothing: if the remote's HEAD points at a
    # branch that does not exist (a bare repository whose default is still `master`
    # while the code lives on `main`), git exits 0 with an empty working tree and only
    # a warning on stderr. Downstream stages would then fail on missing files and
    # report a misleading cause, so check the checkout itself here.
    if [ ! -f "$WORKDIR/clone/$SKILL_NAME/SKILL.md" ]; then
      record FAIL "clone checked out a working tree" "empty checkout - remote HEAD may point at a missing branch"
      echo "      remote HEAD: $(git ls-remote --symref "$CLONE_URL" HEAD 2>/dev/null | awk '/^ref:/{print $2}')" \
           | sed 's/^/      /'
      echo "      branches   : $(git ls-remote --heads "$CLONE_URL" 2>/dev/null | awk '{print $2}' | tr '\n' ' ')" \
           | sed 's/^/      /'
      rm -rf "$WORKDIR"
      SKIP_CLONE=1
    fi
  else
    record FAIL "clone" "could not clone $CLONE_URL"
    rm -rf "$WORKDIR"
    SKIP_CLONE=1
  fi

  if [ "$SKIP_CLONE" -eq 0 ]; then
    record PASS "clone" "$CLONE_URL"
    if bash -n "$WORKDIR/clone/install.sh" 2>/dev/null; then
      record PASS "install.sh syntax" "ok"
    else
      record FAIL "install.sh syntax" "parse error or missing"
    fi
    if [ -f "$WORKDIR/clone/package.sh" ]; then
      bash -n "$WORKDIR/clone/package.sh" 2>/dev/null \
        && record PASS "package.sh syntax" "ok" \
        || record FAIL "package.sh syntax" "parse error"
    fi

    SKILLS_DIR="$WORKDIR/skills" bash "$WORKDIR/clone/install.sh" >/dev/null 2>&1
    N=$(find "$WORKDIR/skills" -type f 2>/dev/null | wc -l | tr -d ' ')
    if [ "$N" -gt 0 ]; then
      record PASS "install from clone" "$N files"
      if [ -f "$WORKDIR/skills/$SKILL_NAME/scripts/check_skill_contract.py" ]; then
        C="$(python3 "$WORKDIR/skills/$SKILL_NAME/scripts/check_skill_contract.py" \
               --skill "$WORKDIR/skills/$SKILL_NAME" 2>&1 | tail -1)"
        case "$C" in
          *CONTRACT_OK*) record PASS "installed skill contract" "CONTRACT_OK" ;;
          *)             record FAIL "installed skill contract" "$C" ;;
        esac
      elif [ -f "$WORKDIR/clone/scripts/check_skill_contract.py" ]; then
        C="$(python3 "$WORKDIR/clone/scripts/check_skill_contract.py" \
               --skill "$WORKDIR/clone/$SKILL_NAME" 2>&1 | tail -1)"
        case "$C" in
          *CONTRACT_OK*) record PASS "clone contract check" "CONTRACT_OK (portable)" ;;
          *)             record FAIL "clone contract check" "$C" ;;
        esac
      fi
    else
      record FAIL "install from clone" "installed 0 files"
    fi
    rm -rf "$WORKDIR"
  fi
fi

# ------------------------------------------------------------------- summary
echo
PASSES=$(printf '%s\n' "${RESULTS[@]}" | grep -c '^PASS|')
FAILS=$(printf '%s\n' "${RESULTS[@]}" | grep -c '^FAIL|')
SKIPS=$(printf '%s\n' "${RESULTS[@]}" | grep -c '^SKIP|')
echo "checks: $PASSES passed, $FAILS failed, $SKIPS skipped"

if [ -n "$JSON_OUT" ]; then
  python3 - "$JSON_OUT" "$SKILL_NAME" "$SLUG" "$FAIL" "$PASSES" "$FAILS" "$SKIPS" "${RESULTS[@]}" <<'PY'
import json, sys
from pathlib import Path
out, skill, slug = sys.argv[1], sys.argv[2], sys.argv[3]
fail, p, f, s = (int(x) for x in sys.argv[4:8])
entries = []
for raw in sys.argv[8:]:
    status, _, rest = raw.partition("|")
    name, _, detail = rest.partition("|")
    entries.append({"status": status, "check": name, "detail": detail})
report = {
    "skill": skill, "repo": slug,
    "passed": p, "failed": f, "skipped": s,
    "verdict": "IN_SYNC" if fail == 0 else "PROBLEMS_FOUND",
    "checks": entries,
}
Path(out).parent.mkdir(parents=True, exist_ok=True)
Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"report: {out}")
PY
fi

if [ "$FAIL" -eq 0 ]; then
  echo "VERDICT: repository fully in sync and reproducible"
else
  echo "VERDICT: problems found"
fi
exit $FAIL
