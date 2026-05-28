#!/usr/bin/env bash
# Docs-drift Stop hook.
# Flags when Python code under modules/<X>/ changed in the working tree without
# a matching docs/modules/<X>.md (or docs/modules/<X>/**.md) edit.
# Non-blocking by design: exits 2 so Claude sees the reminder and can react,
# but the user can always acknowledge and move on.

set -euo pipefail

repo="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$repo"

# All uncommitted changes, INCLUDING untracked files (so brand-new doc files count).
# git status --porcelain output: "XY path" — we want the path, so strip first 3 chars.
# Silent-fail if not a git repo.
changed=$(git status --porcelain -uall 2>/dev/null | awk '{print substr($0, 4)}' || true)
[ -z "$changed" ] && exit 0

# Python edits inside modules/<X>/
py_changes=$(echo "$changed" | grep -E '^modules/[^/]+/.*\.py$' || true)
[ -z "$py_changes" ] && exit 0

# Unique modules with .py edits
modules_edited=$(echo "$py_changes" | awk -F/ '{print $2}' | sort -u)

drifting=()
while IFS= read -r module; do
  [ -z "$module" ] && continue
  # matches docs/modules/<module>.md OR docs/modules/<module>/**.md
  touched=$(echo "$changed" | grep -E "^docs/modules/${module}(\\.md|/.*\\.md)$" || true)
  [ -z "$touched" ] && drifting+=("$module")
done <<< "$modules_edited"

if [ ${#drifting[@]} -gt 0 ]; then
  {
    echo "📝 Docs drift detected — code changed but docs not touched:"
    for m in "${drifting[@]}"; do
      if [ -d "docs/modules/$m" ]; then
        echo "  - modules/$m/  →  docs/modules/$m/"
      else
        echo "  - modules/$m/  →  docs/modules/$m.md"
      fi
    done
    echo ""
    echo "Action: update the matching doc now, OR reply noting why the change is trivial."
    echo "(Trivial = typo/formatter/logs/dead-code removal. See CLAUDE.md 'Documentation freshness'.)"
  } >&2
  exit 2
fi

exit 0
