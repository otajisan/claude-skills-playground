#!/usr/bin/env bash
set -euo pipefail

SKILLS_DIR="$HOME/.claude/skills"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$SKILLS_DIR"

installed=0
skipped=0

for skill_dir in "$REPO_DIR"/*/; do
  [ -f "$skill_dir/SKILL.md" ] || continue

  skill_name="$(basename "$skill_dir")"
  target="$SKILLS_DIR/$skill_name"

  # Already the correct symlink
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$skill_dir" ]; then
    echo "  skip: $skill_name (already linked)"
    skipped=$((skipped + 1))
    continue
  fi

  # Existing file or directory — back up before replacing
  if [ -e "$target" ]; then
    backup_dir="$REPO_DIR/.backups"
    mkdir -p "$backup_dir"
    backup="$backup_dir/${skill_name}.bak.$(date +%Y%m%d%H%M%S)"
    echo "  backup: $target -> $backup"
    mv "$target" "$backup"
  fi

  ln -s "$skill_dir" "$target"
  echo "  link: $skill_name -> $skill_dir"
  installed=$((installed + 1))
done

echo ""
echo "done: ${installed} linked, ${skipped} skipped"
