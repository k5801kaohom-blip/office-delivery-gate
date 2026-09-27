#!/usr/bin/env bash
# Package this skill into a distributable ZIP archive.
#
# Auto-detects the skill from the SKILL.md in this repository. Proves the archive
# actually contains SKILL.md before reporting success: a zip that lost the skill
# payload still looks like a successful build.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SKILL_MD="$(find "$ROOT" -maxdepth 2 -name SKILL.md -not -path '*/.git/*' 2>/dev/null | head -1)"
if [ -z "$SKILL_MD" ]; then
  echo "error: no SKILL.md found under $ROOT" >&2
  exit 1
fi
SOURCE_DIR="$(dirname "$SKILL_MD")"
SKILL_NAME="$(basename "$SOURCE_DIR")"
DIST_DIR="${ROOT}/dist"
OUTPUT="${DIST_DIR}/${SKILL_NAME}-skill.zip"

mkdir -p "$DIST_DIR"
rm -f "$OUTPUT"

(
  cd "$ROOT"
  zip -r -9 -q "$OUTPUT" "$SKILL_NAME" \
    -x '*/__pycache__/*' '*.pyc' '*.pyo' '*/.DS_Store' '*/.git/*'
)

if ! unzip -l "$OUTPUT" | grep -q "${SKILL_NAME}/SKILL.md"; then
  echo "error: archive is missing ${SKILL_NAME}/SKILL.md" >&2
  exit 1
fi

SIZE="$(du -h "$OUTPUT" | cut -f1)"
echo "packaged: $OUTPUT  ($SIZE)"
echo
unzip -l "$OUTPUT" | tail -n +4 | head -n -2