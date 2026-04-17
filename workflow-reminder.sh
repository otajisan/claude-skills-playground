#!/bin/bash
# ~/.claude/hooks/workflow-reminder.sh
#
# Stopイベント時に「フィーチャーブランチにコミットあり・PRなし」を検知し、
# review → review-apply → readme-sync → pr-create のワークフローをClaudeに促す。

INPUT=$(cat)

# ── 1. 無限ループ防止 ──────────────────────────────────────────
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  exit 0
fi

# ── 2. gitリポジトリでなければスキップ ────────────────────────
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

# ── 3. ベースブランチ（main / master / develop）ならスキップ ──
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null)
if [ -z "$CURRENT_BRANCH" ]; then
  exit 0
fi

BASE_BRANCH=""
for candidate in main master develop; do
  if git show-ref --verify --quiet "refs/heads/$candidate"; then
    BASE_BRANCH="$candidate"
    break
  fi
done

if [ -z "$BASE_BRANCH" ] || [ "$CURRENT_BRANCH" = "$BASE_BRANCH" ]; then
  exit 0
fi

# ── 4. ベースブランチより先にコミットがなければスキップ ────────
COMMITS_AHEAD=$(git rev-list "${BASE_BRANCH}..HEAD" --count 2>/dev/null || echo "0")
if [ "$COMMITS_AHEAD" = "0" ]; then
  exit 0
fi

# ── 5. PRがすでに存在すればスキップ ───────────────────────────
if command -v gh &>/dev/null; then
  PR_COUNT=$(gh pr list --head "$CURRENT_BRANCH" --json number --jq 'length' 2>/dev/null || echo "0")
  if [ "$PR_COUNT" != "0" ]; then
    exit 0
  fi
fi

# ── 6. ワークフローリマインダーを出力 ─────────────────────────
cat >&2 <<EOF
──────────────────────────────────────────────
📋 ワークフローリマインダー
──────────────────────────────────────────────
ブランチ      : $CURRENT_BRANCH
未PR コミット : $COMMITS_AHEAD 件

実装作業が完了していれば、以下のワークフローを順に実行してください:

  1. /review         — コードレビュー・品質チェック
  2. /review-apply   — レビュー指摘を反映してコードを精錬
  3. /readme-sync    — README更新（変更内容に応じて）
  4. /pr-create      — PR作成

各ステップは前ステップの出力を引き継げます。
(例: /review-apply は直前の /review 結果をそのまま入力として使える)

すでに完了済み・不要な場合は「スキップ」と伝えてください。
──────────────────────────────────────────────
EOF

exit 2
