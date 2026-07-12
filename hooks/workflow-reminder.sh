#!/usr/bin/env bash
# ~/.claude/hooks/workflow-reminder.sh
#
# Stopイベント時に git 状態を判定し、実装完了ワークフローをClaudeに促す。
#   State A: ベースブランチ上に変更あり        → 作業ブランチの作成を促す
#   State B: フィーチャーブランチでコミットあり・PRなし → 完了ワークフロー全文を促す
#
# フック自体はスキルを実行できない。stderr へ指示を出力し exit 2 で Stop をブロックすると、
# その指示が Claude に差し戻され、Claude がワークフローを実行する。

INPUT=$(cat)

# ── 0. jq 未導入環境ではスキップ ───────────────────────────────
if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

# ── 1. 無限ループ防止 ──────────────────────────────────────────
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  exit 0
fi

# ── 2. gitリポジトリでなければスキップ ────────────────────────
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

# ── 3. 現在ブランチを取得 ─────────────────────────────────────
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null)
if [ -z "$CURRENT_BRANCH" ]; then
  exit 0
fi

# ── 4. ベースブランチ（main / master / develop）を検出 ────────
BASE_BRANCH=""
for candidate in main master develop; do
  if git show-ref --verify --quiet "refs/heads/$candidate"; then
    BASE_BRANCH="$candidate"
    break
  fi
done

if [ -z "$BASE_BRANCH" ]; then
  exit 0
fi

# ── State A: ベースブランチ上に変更あり → 作業ブランチ作成を促す ──
if [ "$CURRENT_BRANCH" = "$BASE_BRANCH" ]; then
  CHANGES=$(git status --porcelain 2>/dev/null)
  if [ -z "$CHANGES" ]; then
    exit 0
  fi
  CHANGE_COUNT=$(printf '%s\n' "$CHANGES" | grep -c .)

  cat >&2 <<EOF
──────────────────────────────────────────────
📋 実装完了ワークフロー — ① 作業ブランチの作成
──────────────────────────────────────────────
現在ブランチ : $CURRENT_BRANCH （ベースブランチ）
変更         : $CHANGE_COUNT 件（未コミット/未追跡）

ベースブランチ上に変更があります。実装が完了していれば、
まず作業ブランチを作成してください:

  1. git checkout -b <type>/<簡潔な説明>   （例: feat/xxx, fix/xxx）
  2. 変更をステージ & コミット

コミットまで済ませると、次の停止時に残りのワークフロー
（レビュー→修正ループ → /readme-sync → /pr-create）を自動で案内します。

まだ作業途中の場合は「スキップ」と伝えてください。
──────────────────────────────────────────────
EOF
  exit 2
fi

# ── State B: フィーチャーブランチ ─────────────────────────────
# 5. ベースブランチより先にコミットがなければスキップ
COMMITS_AHEAD=$(git rev-list "${BASE_BRANCH}..HEAD" --count 2>/dev/null || echo "0")
if [ "$COMMITS_AHEAD" = "0" ]; then
  exit 0
fi

# 6. PRがすでに存在すればスキップ
if command -v gh &>/dev/null; then
  PR_COUNT=$(gh pr list --head "$CURRENT_BRANCH" --json number --jq 'length' 2>/dev/null || echo "0")
  if [ "$PR_COUNT" != "0" ]; then
    exit 0
  fi
fi

# 7. 実装完了ワークフローを出力
cat >&2 <<EOF
──────────────────────────────────────────────
📋 実装完了ワークフロー
──────────────────────────────────────────────
ブランチ      : $CURRENT_BRANCH
未PR コミット : $COMMITS_AHEAD 件

実装が完了していれば、以下を順に実行してください（不要・完了済みならスキップ可）:

【1】レビュー → 修正ループ（対応必須の指摘が尽きるまで反復）
   a. /code-review        — ワーキング/ブランチ差分をレビュー
   b. /codex:review --background --base $BASE_BRANCH
        ※ codex はユーザーが手入力で実行する必要があります（Claudeからは自動起動不可）。
          実行を依頼し、完了後 /codex:status で結果を取得して d の入力に含めてください。
   c. セキュリティ観点レビュー
        （security-reviewer エージェント、または /security-review）
   d. /review-apply       — a〜c の対応必須の指摘を実装・コミット
   e. 新たな対応必須の指摘が出なくなるまで a〜d を繰り返す

【2】/readme-sync          — 最終コードに合わせて README を更新

【3】/pr-create            — PR 本文を生成
        → git push -u origin $CURRENT_BRANCH && gh pr create でPRを作成

すでに完了済み・不要な場合は「スキップ」と伝えてください。
──────────────────────────────────────────────
EOF

exit 2
