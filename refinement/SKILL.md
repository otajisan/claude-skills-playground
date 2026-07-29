---
name: refinement
description: GitHub IssueをコードベースとすりあわせてIssueをrefinementする。「refinement」「Issueを整理して」「実装プランを立てて」「Issue #xxx を読み込んで」などと言われたら必ずこのSkillを使う。Issue番号またはURLを引数に取る。実装プランの書き戻しに加えてラベル/Assignee/Project/マイルストーン/Issue Typeの欠けも埋める。
allowed-tools: Bash(gh issue view:*), Bash(gh issue edit:*), Bash(gh issue comment:*), Bash(gh auth status:*), Bash(gh repo view:*), Bash(gh label list:*), Bash(gh api:*), Bash(gh project list:*), Bash(git log:*), Bash(git branch:*), Bash(find:*), Bash(grep:*), Read, Write, Grep, Glob
---

# Refinement Skill

Issue番号またはURLをコードベースとすりあわせ、実装プランをIssueに書き戻す。
あわせて **後から一覧・ボードで追える状態にする**（ラベル / Assignee / Project / マイルストーン / Issue Type）。

**引数**: `$ARGUMENTS` にIssue番号（例: `123`）またはURL（例: `https://github.com/org/repo/issues/123`）が渡される。

---

## Step 1: Issueを読み込む

```
Issue内容: !`gh issue view $ARGUMENTS --json number,title,body,labels,assignees,milestone,projectItems,comments,url`
現在のブランチ: !`git branch --show-current`
最近のコミット: !`git log --oneline -10`
リポジトリ情報: !`gh repo view --json nameWithOwner,owner`
```

URLが渡された場合はそこから **`owner` / `repo` / Issue番号を明示的に抽出**してから後続の `gh` を叩く。
以降の手順では抽出した番号を `$NUM` として扱う。

> `gh api` の `{owner}` / `{repo}` は自動展開されるが `{number}` は展開されない。Issue番号は必ず自分で埋める。

---

## Step 2: コードベースを理解する

Issueの内容を踏まえ、**関連しそうな範囲を優先**してコードベースを調査する。全体を盲目的に読むのではなく、Issueのキーワード・ドメイン・ファイル名の手がかりから絞り込む。

```
プロジェクト構造: !`find . -maxdepth 4 -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/build/*' -not -path '*/dist/*'`
```

Issueのキーワードから関連コードを絞り込むには Grep / Glob を使う。該当ファイルは Read で読み込む。

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

## Step 4: Issue本文にプランを書き戻す

**本文は必ずファイルに書き出して `--body-file` で渡す。**
`--body "$(cat <<'EOF' ... EOF)"` のようなヒアドキュメント方式は使わない。元本文に含まれるバッククォート・`$`・`EOF` 行・末尾改行で壊れる。
また **元本文を手で書き写さない。** 必ず API から取得した実物を土台にする（写し間違いによる本文欠落を防ぐ）。

```bash
# 1. 元の本文をそのままファイルに退避する
gh issue view "$NUM" --json body -q .body > <scratchpad>/issue-$NUM-original.md

# 2. Read で退避ファイルを確認し、Write で「元本文 + 区切り + 実装プラン」を組み立てる
#    → <scratchpad>/issue-$NUM-body.md

# 3. --body-file で更新する
gh issue edit "$NUM" --body-file <scratchpad>/issue-$NUM-body.md
```

### 追記するフォーマット

```markdown
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
```

> **元の本文は必ず残す**。上書きではなく、`---` 区切りの下に追記する形にする。
> 2回目以降の refinement で既に `## 🗺️ 実装プラン` セクションがある場合は、重複して追記せず **既存セクションを差し替える**。

---

## Step 5: メタ情報の欠けを埋める

refinement は「後から追えるIssueにする」工程でもある。Step 1 で取得した `labels` / `assignees` / `milestone` / `projectItems` を見て、欠けているものを補完する。

Issue Type は `gh issue view --json` に該当フィールドが無いので REST で確認する：

```bash
gh api "repos/{owner}/{repo}/issues/$NUM" -q '.type.name'
```

### 候補の洗い出し

**存在しない名前を渡すとコマンドが失敗する。** 必ず実在する候補を列挙してから選ぶ。

```bash
gh label list --limit 100                                                        # ラベル（description で意図を確認）
gh api "repos/{owner}/{repo}/milestones?state=open" --paginate -q '.[].title'    # マイルストーン
gh api "orgs/{owner}/issue-types" -q '.[].name'                                  # Issue Type（owner が org の場合のみ）
gh project list --owner OWNER                                                    # Project（`project` スコープが必要）
```

### 補完方針

| 項目 | 方針 | コマンド |
|---|---|---|
| **ラベル** | 「種別」（`feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `perf` / `ci` 相当）＋「文脈」（対象サービス・領域・調査 / コスト等）で**複数付与** | `gh issue edit "$NUM" --add-label "<name>"` |
| **Assignee** | 実装担当が決まっていれば設定。自分が担当なら `@me` | `gh issue edit "$NUM" --add-assignee @me` |
| **Project** | リポジトリ / owner で現役運用されているボードに載せる | `gh issue edit "$NUM" --add-project "<title>"` |
| **マイルストーン** | **必ず探してから判断する。** 親テーマに該当するものがあれば紐づける。該当が無ければ付けなくてよいが「探さずに省略」はしない | `gh issue edit "$NUM" -m "<title>"` |
| **Issue Type** | **Issue には必ず設定する。** `gh` に `--type` フラグは無いため REST で設定する | `gh api -X PATCH "repos/{owner}/{repo}/issues/$NUM" -f type=<Type>` |

- `--add-*` は追加のみなので既存の値を消さない。`-m` は**置換**なので既存マイルストーンを上書きしないか確認する
- 親子構造がある Issue は sub-issue 機能で紐づける（`gh` に専用フラグは無いため GraphQL `addSubIssue` または Web UI を使う）
- Project 紐付けには token の `project` スコープが必要。`gh auth status` で確認し、不足していれば `gh auth refresh -h github.com -s project` の実行をユーザーに依頼する（**非対話実行では `-h` を省くと `--hostname required` で失敗する**）。付与できない場合は Project 以外を埋めて、Project 未設定である旨を報告する

---

## 共通方針

- Step 3 の質問は**一度にまとめて出す**。小出しにしない
- 実装ステップは GitHub の task list（`- [ ]`）形式にして、そのままIssueのチェックボックスとして使えるようにする
- 影響範囲が広い場合は Mermaid でファイル間の依存関係を図示してもよい
- `$ARGUMENTS` が空の場合は「Issue番号またはURLを教えてください」と聞く
- 実装プランはプランモードの承認で終わらせず、**必ず Issue 本文に書き戻す**（会話だけで消えるとレビュー・引き継ぎで追えない）
- 最後の報告では Issue URL とあわせて、**書き戻したセクションと、埋めた / 埋めなかったメタ情報（およびその理由）** を明示する
