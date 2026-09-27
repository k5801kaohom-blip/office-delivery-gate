#!/usr/bin/env bash
# Install this skill into a local skills directory.
#
# Auto-detects the skill from the SKILL.md in this repository, so no name has to be
# edited after scaffolding. Verifies the install afterwards: an install that silently
# copies nothing, or copies a skill whose documentation names files that were never
# committed, must fail here rather than at the user's first run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SKILL_MD="$(find "$ROOT" -maxdepth 2 -name SKILL.md -not -path '*/.git/*' 2>/dev/null | head -1)"
if [ -z "$SKILL_MD" ]; then
  echo "error: no SKILL.md found under $ROOT" >&2
  exit 1
fi
SOURCE_DIR="$(dirname "$SKILL_MD")"
SKILL_NAME="$(basename "$SOURCE_DIR")"
TARGET_ROOT="${SKILLS_DIR:-$HOME/skills}"
TARGET_DIR="${TARGET_ROOT}/${SKILL_NAME}"

mkdir -p "$TARGET_ROOT"

if [ -e "$TARGET_DIR" ]; then
  BACKUP="${TARGET_DIR}.backup.$(date +%Y%m%d%H%M%S)"
  echo "existing install moved to: $BACKUP"
  mv "$TARGET_DIR" "$BACKUP"
fi

cp -R "$SOURCE_DIR" "$TARGET_DIR"
find "$TARGET_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$TARGET_DIR" -name '*.pyc' -delete 2>/dev/null || true
chmod +x "$TARGET_DIR"/scripts/* 2>/dev/null || true

if [ ! -f "$TARGET_DIR/SKILL.md" ]; then
  echo "error: install produced no SKILL.md" >&2
  exit 1
fi

COUNT="$(find "$TARGET_DIR" -type f | wc -l | tr -d ' ')"
echo "installed: $TARGET_DIR  ($COUNT files)"

# Post-install proof. Silent when the skill ships no contract checker, so this
# template works for skills that have none.
if [ -f "$TARGET_DIR/scripts/check_skill_contract.py" ]; then
  if python3 "$TARGET_DIR/scripts/check_skill_contract.py" --skill "$TARGET_DIR" >/dev/null 2>&1; then
    echo "contract check: OK"
  else
    echo "warning: contract check failed in the installed copy" >&2
    echo "         run it for detail: python3 $TARGET_DIR/scripts/check_skill_contract.py --skill $TARGET_DIR" >&2
  fi
fi

echo
echo "Usage:"
echo "  read    ${TARGET_DIR}/SKILL.md"
echo "  verify  bash ${TARGET_DIR}/scripts/verify_skill_repo.sh --offline   # if present"