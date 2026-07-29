---
name: pr-create
description: PRを作成する。git diffを分析して概要・技術スタック・Mermaid図解を含む読みやすいPR説明を生成し、ラベル/Assignee/Project/マイルストーン/関連Issueといったメタ情報まで必ず埋める。「PRを作って」「PR作成」「プルリク」などと言われたら必ずこのSkillを使う。
allowed-tools: Bash(git diff:*), Bash(git log:*), Bash(git status:*), Bash(git branch:*), Bash(gh auth status:*), Bash(gh repo view:*), Bash(gh label list:*), Bash(gh api:*), Bash(gh project list:*), Bash(gh project field-list:*), Bash(gh project item-list:*), Bash(gh project item-edit:*), Bash(gh pr create:*), Bash(gh pr edit:*), Bash(gh pr view:*), Read, Write
---

# PR作成 Skill

**PR は「本文を書いて終わり」にしない。** 本文と同じ重みでメタ情報（ラベル / Assignee / Project / マイルストーン / 関連 Issue）を埋める。
後から一覧やボードで追えない PR を作らないことが、この Skill の目的の半分である。

---

## 1. コンテキスト収集

まず以下を実行して変更内容を把握する：

- 現在のブランチ: !`git branch --show-current`
- リポジトリ情報: !`gh repo view --json nameWithOwner,defaultBranchRef,owner`
- ベースブランチとの差分サマリ: !`git diff main...HEAD --stat 2>/dev/null || git diff master...HEAD --stat 2>/dev/null || git diff develop...HEAD --stat`
- 詳細差分: !`git diff main...HEAD 2>/dev/null || git diff master...HEAD 2>/dev/null || git diff develop...HEAD`
- コミット一覧: !`git log main..HEAD --oneline 2>/dev/null || git log master..HEAD --oneline 2>/dev/null || git log develop..HEAD --oneline`

> ベースブランチは `gh repo view` の `defaultBranchRef` を優先し、取得できない場合は `main` → `master` → `develop` の順にフォールバックする。いずれとも異なる場合はブランチ名を読み替えて再実行する。
> `$ARGUMENTS` に追加指示がある場合はそちらを優先する。

### gh 認証スコープの確認

Project への紐付けには token の `project` スコープが必要。

```bash
gh auth status   # Token scopes に project が含まれるか確認
```

含まれていなければユーザーに以下の実行を依頼する（**非対話実行では `-h` を省くと `--hostname required` で失敗する**）：

```bash
gh auth refresh -h github.com -s project
```

スコープが無いまま `-p` を付けると PR 作成そのものが失敗する。付与できない場合は Project 以外のメタ情報を埋めて作成し、Project 未設定である旨を報告する。

---

## 2. メタ情報の候補を洗い出す（本文を書く前に）

**存在しない名前を推測で渡すと `gh pr create` は失敗する。** 必ず実在する候補を列挙してから選ぶ。

```bash
# ラベル一覧（description を読んで意図に合うものを選ぶ）
gh label list --limit 100

# マイルストーン一覧（open のみ）
gh api "repos/{owner}/{repo}/milestones?state=open" --paginate -q '.[] | "\(.number)\t\(.title)"'

# このリポジトリに紐づく Project（Projects v2）
gh api graphql -f query='
  query($owner:String!, $repo:String!) {
    repository(owner:$owner, name:$repo) {
      projectsV2(first:20) { nodes { number title closed } }
    }
  }' -f owner=OWNER -f repo=REPO -q '.data.repository.projectsV2.nodes[] | select(.closed==false)'

# 上で見つからない場合は owner (org / user) 単位で探す
gh project list --owner OWNER
```

洗い出した結果から、以下の方針で決める。

| 項目 | 決め方 |
|---|---|
| **ラベル** | **複数付与する。**「種別」（`feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `perf` / `ci` 相当）＋「文脈」（対象サービス・領域・調査 / コスト等）の組み合わせ。既存ラベルの description を読んで選ぶ |
| **Assignee** | **常に `@me`**（このセッションの実行者本人）。他者をアサインする指示がある場合のみ login を明示する |
| **Project** | リポジトリ / owner で現役運用されているボードに紐づける。候補が複数あって判別できない場合のみユーザーに確認する |
| **マイルストーン** | **必ず探してから判断する。** 親テーマに該当するものがあれば紐づける。該当が無ければ付けなくてよいが「探さずに省略」はしない |
| **関連 Issue** | 本文に記載する（次節） |

> **Issue Type は PR には存在しない概念**なので設定不要。Issue 側は別途 Type を埋める（`gh` に `--type` フラグは無いので `gh api -X PATCH repos/{owner}/{repo}/issues/<N> -f type=<Type>` で設定する。選択可能な Type は org 定義に依存するため事前に確認する）。

---

## 3. PRフォーマット

以下のMarkdown構成でPR本文を生成する。

### 概要

- レビュアーが **3分で全体を把握できる** 箇条書き（3〜5項目）
- 「何を」「なぜ」変えたかを中心に記述
- 文章は短く。冗長な説明は不要

### 関連 Issue（必須）

対象 Issue との紐付けを **必ず本文に書く**。書式で意図を出し分ける。

| ケース | 書式 |
|---|---|
| その Issue を解決する実装 PR | `Closes #<N>` （マージ時に自動クローズ） |
| クローズ済み Issue への hotfix / revert / 追加対応 | `Related to #<N>` / `Follow-up of #<N>` |
| 親子構造がある | 親 Issue を `Related to #<N>` で示す（Issue 側は sub-issue 機能も併用する） |

**クローズ済み Issue が対象でも省略しない。** 再度紐づけてトレーサビリティを担保する。
紐づく Issue が本当に存在しない場合は「関連 Issue なし（理由）」と明記する。

### 利用技術スタック

- PR内で使用・変更した技術をハイライト（例: `Kotlin x Spring Boot`, `Python`, `npm-check-updates`）
- **新規採用技術**がある場合は `[技術名](参考URL)` 形式でリンクを付与

### 変更の図解（必要な場合）

複雑な処理フロー・アーキテクチャ変更・データの流れがある場合は Mermaid で図解する。
シンプルなバグ修正や軽微な変更には不要。

```mermaid
（変更内容に応じて flowchart / sequenceDiagram / erDiagram などを選択）
```

### その他

特記事項がある場合のみ記述：
- 破壊的変更（Breaking Changes）
- マイグレーション手順
- パフォーマンスへの影響
- レビュー時に特に確認してほしい箇所

---

## 4. PR を作成する

**本文は必ず Write でファイル化し `--body-file` 経由で渡す。** ヒアドキュメントや `--body` に直接埋め込むと、バッククォート・`$`・改行のエスケープ事故で本文が壊れる。

```bash
# 1. Write ツールで本文をファイルに書き出す（例: <scratchpad>/pr-body.md）
# 2. メタ情報を全部付けて作成する
gh pr create \
  --title "<type>: <description>" \
  --body-file <path/to/pr-body.md> \
  -a @me \
  -l "<label1>" -l "<label2>" \
  -m "<milestone>" \
  -p "<project title>"
```

- `-l` / `-a` / `-p` は**繰り返し指定で複数付与**できる
- 該当が無い項目のフラグは省略する（空文字を渡さない）
- リポジトリに PR テンプレートがあれば本文構成に取り込む（`.github/pull_request_template.md` / `.github/PULL_REQUEST_TEMPLATE/`）

### 既存 PR への後付け

```bash
gh pr edit <PR番号 or URL> \
  --add-label "<label>" \
  --add-assignee @me \
  --add-project "<project title>" \
  --milestone "<milestone>"
```

---

## 5. 作成後の確認

```bash
gh pr view <PR番号> --json number,title,url,labels,assignees,milestone,projectItems
```

ラベル / Assignee / マイルストーン / Project が意図通り入っているか確認する。空の項目があれば `gh pr edit` で埋める。

### Project の Status を確認する

Project に追加しただけでは Status が未設定でボードの「No Status」に落ちる。初期カラム（`To do` 相当）を設定する。

```bash
# 現在の Status と item ID を確認
gh api graphql -f query='
  query($owner:String!, $repo:String!, $number:Int!) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$number) {
        projectItems(first:10) {
          nodes {
            id
            project { id number title }
            fieldValueByName(name:"Status") {
              ... on ProjectV2ItemFieldSingleSelectValue { name }
            }
          }
        }
      }
    }
  }' -f owner=OWNER -f repo=REPO -F number=PR_NUMBER

# 未設定なら Status フィールドと選択肢の ID を引いて設定する
gh project field-list <project number> --owner OWNER --format json \
  -q '.fields[] | select(.name=="Status")'

gh project item-edit \
  --project-id <PVT_... (project id)> \
  --id <PVTI_... (item id)> \
  --field-id <PVTSSF_... (Status field id)> \
  --single-select-option-id <option id>
```

> Status の選択肢名（`To do` / `In progress` / `Done` など）は Project ごとに異なる。`field-list` の結果から実在する選択肢を選ぶ。Status フィールドが無い Project では何もしない。

---

## 生成方針

- **文字量は最小限**。箇条書きと図解を優先し、散文は避ける
- Mermaid図は「あると理解が速くなる」場合のみ使う。無理に入れない
- 技術スタックのリンクは公式ドキュメント・GitHubリポジトリを優先
- **メタ情報は「付け忘れ」ではなく「探して判断した結果」にする。** 候補を列挙せずに省略してはいけない
- 最後の報告では、PR URL とあわせて **付与したラベル / Assignee / Project / マイルストーン / 関連 Issue、および付けなかった項目とその理由** を明示する
