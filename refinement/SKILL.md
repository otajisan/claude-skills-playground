---
name: refinement
description: GitHub IssueをコードベースとすりあわせてIssueをrefinementする。「refinement」「Issueを整理して」「実装プランを立てて」「Issue #xxx を読み込んで」などと言われたら必ずこのSkillを使う。Issue番号またはURLを引数に取る。
allowed-tools: Bash(gh issue view:*), Bash(gh issue edit:*), Bash(gh issue comment:*), Bash(git log:*), Bash(git branch:*), Bash(find:*), Bash(cat:*), Bash(grep:*)
---

# Refinement Skill

Issue番号またはURLをコードベースとすりあわせ、実装プランをIssueに書き戻す。

**引数**: `$ARGUMENTS` にIssue番号（例: `123`）またはURL（例: `https://github.com/org/repo/issues/123`）が渡される。

---

## Step 1: Issueを読み込む

```
Issue内容: !`gh issue view $ARGUMENTS --json number,title,body,labels,assignees,comments`
現在のブランチ: !`git branch --show-current`
最近のコミット: !`git log --oneline -10`
```

URLが渡された場合はそこからIssue番号を抽出して使う。

---

## Step 2: コードベースを理解する

Issueの内容を踏まえ、**関連しそうな範囲を優先**してコードベースを調査する。全体を盲目的に読むのではなく、Issueのキーワード・ドメイン・ファイル名の手がかりから絞り込む。

```
プロジェクト構造:       !`find . -maxdepth 4 -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/build/*' -not -path '*/dist/*'`
Issueに関連するコード:  grep -r "{Issueのキーワード}" --include="*.kt" --include="*.py" --include="*.ts" -l 2>/dev/null | head -20
```

必要に応じて関連ファイルを `cat` で読み込む。

---

## Step 3: 実装プランのドラフトを作成し、質問する

調査結果をもとに以下を作成し、**ユーザーに提示して確認・ブラッシュアップを行う**。

### 提示フォーマット

---

**📋 Issue #[番号] 理解サマリ**

> Issueが何を求めているか、1〜3文で要約。

**🔍 コードベース調査結果**

- 影響範囲（変更が必要なファイル・モジュール）
- 既存の関連実装（再利用できるもの・競合するもの）
- 懸念点・考慮すべき制約

**🗺️ 実装プラン（ドラフト）**

1. [具体的なステップ]
2. [具体的なステップ]
3. ...

**❓ 確認したい点**

- [決定が必要な事項や仕様の曖昧さ]
- [技術的な選択肢がある場合はオプションを提示]

---

ユーザーの回答をもとにプランをブラッシュアップする。  
「問題なし」「このままで」などの承認が得られたら **Step 4** に進む。

---

## Step 4: IssueをRefinementする

確定したプランをもとに、元のIssueを以下のフォーマットで更新する。

```bash
gh issue edit $ARGUMENTS --body "$(cat <<'EOF'
{元のIssue本文をそのまま残す}

---

## 🗺️ 実装プラン

### 概要
{何をどう実装するかを3〜5文で}

### 影響範囲
| ファイル / モジュール | 変更内容 |
|---|---|
| `path/to/file.kt` | 〇〇の追加 |

### 実装ステップ
1. [ ] {具体的なタスク}
2. [ ] {具体的なタスク}
3. [ ] {具体的なタスク}

### 技術的な考慮点
- {採用する実装方針とその理由}
- {既存コードとの整合性・注意点}

### 完了条件
- [ ] {テスト・動作確認の基準}

EOF
)"
```

> **元の本文は必ず残す**。上書きではなく、`---` 区切りの下に追記する形にする。

---

## 共通方針

- Step 3 の質問は**一度にまとめて出す**。小出しにしない
- 実装ステップは GitHub の task list（`- [ ]`）形式にして、そのままIssueのチェックボックスとして使えるようにする
- 影響範囲が広い場合は Mermaid でファイル間の依存関係を図示してもよい
- `$ARGUMENTS` が空の場合は「Issue番号またはURLを教えてください」と聞く
