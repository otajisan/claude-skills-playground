#!/usr/bin/env bash
set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SKILLS_DIR="$CLAUDE_DIR/skills"
HOOKS_DIR="$CLAUDE_DIR/hooks"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$REPO_DIR/.backups"

mkdir -p "$SKILLS_DIR" "$HOOKS_DIR"

installed=0
skipped=0

backup_existing() {
  local target="$1"
  local label="$2"
  mkdir -p "$BACKUP_DIR"
  local backup="$BACKUP_DIR/${label}.bak.$(date +%Y%m%d%H%M%S)"
  echo "  backup: $target -> $backup"
  mv "$target" "$backup"
}

link_dir() {
  local src="$1"
  local target_dir="$2"
  local name
  name="$(basename "$src")"
  local target="$target_dir/$name"

  if [ -L "$target" ] && [ "$(readlink "$target")" = "$src" ]; then
    echo "  skip: $name (already linked)"
    skipped=$((skipped + 1))
    return
  fi

  if [ -e "$target" ]; then
    backup_existing "$target" "$name"
  fi

  ln -s "$src" "$target"
  echo "  link: $name -> $src"
  installed=$((installed + 1))
}

# ── Skills ────────────────────────────────────────────────────
echo "▶ skills"
for skill_dir in "$REPO_DIR"/*/; do
  [ -f "$skill_dir/SKILL.md" ] || continue
  # Strip trailing slash for readlink comparison
  link_dir "${skill_dir%/}" "$SKILLS_DIR"
done

# ── Hook scripts ──────────────────────────────────────────────
echo ""
echo "▶ hooks (scripts)"
if [ -d "$REPO_DIR/hooks" ]; then
  shopt -s nullglob
  for hook_src in "$REPO_DIR/hooks"/*.sh; do
    chmod +x "$hook_src"
    link_dir "$hook_src" "$HOOKS_DIR"
  done
  shopt -u nullglob
else
  echo "  (no hooks/ directory)"
fi

# ── Merge hook config into settings.json ──────────────────────
echo ""
echo "▶ hooks (settings.json)"
HOOKS_CONFIG="$REPO_DIR/hooks/hooks.json"
if [ ! -f "$HOOKS_CONFIG" ]; then
  echo "  (no hooks/hooks.json — nothing to merge)"
elif ! command -v jq >/dev/null 2>&1; then
  echo "  ! jq not found — skipping settings.json merge"
  echo "    install jq, then re-run: brew install jq"
else
  if [ ! -f "$SETTINGS_FILE" ]; then
    echo '{}' > "$SETTINGS_FILE"
  fi

  # Snapshot before modifying, so user can recover prior state.
  mkdir -p "$BACKUP_DIR"
  cp "$SETTINGS_FILE" "$BACKUP_DIR/settings.json.bak.$(date +%Y%m%d%H%M%S)"

  added=0
  deduped=0

  # hooks.json is a map of { EventName: [ hookEntry, ... ] }.
  # For each entry, append under .hooks.<Event>[0].hooks if its command is
  # not already present anywhere under that event.
  while IFS= read -r event; do
    while IFS= read -r entry; do
      cmd="$(printf '%s' "$entry" | jq -r '.command')"
      exists="$(jq --arg e "$event" --arg c "$cmd" '
        [ (.hooks // {})[$e] // [] | .[] | .hooks // [] | .[] | .command ]
        | index($c) != null
      ' "$SETTINGS_FILE")"

      if [ "$exists" = "true" ]; then
        echo "  skip: [$event] $cmd (already configured)"
        deduped=$((deduped + 1))
        continue
      fi

      jq --arg e "$event" --argjson h "$entry" '
        .hooks //= {}
        | .hooks[$e] //= []
        | .hooks[$e] += [ { hooks: [ $h ] } ]
      ' "$SETTINGS_FILE" > "$SETTINGS_FILE.tmp"
      mv "$SETTINGS_FILE.tmp" "$SETTINGS_FILE"
      echo "  add:  [$event] $cmd"
      added=$((added + 1))
    done < <(jq -c --arg e "$event" '.[$e][]' "$HOOKS_CONFIG")
  done < <(jq -r 'keys[]' "$HOOKS_CONFIG")

  echo "  settings.json: ${added} added, ${deduped} already present"
fi

echo ""
echo "done: ${installed} linked, ${skipped} skipped"
