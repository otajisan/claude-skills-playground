---
name: pr-create
description: PRを作成する。git diffを分析して概要・技術スタック・Mermaid図解を含む読みやすいPR説明を生成する。「PRを作って」「PR作成」「プルリク」などと言われたら必ずこのSkillを使う。
allowed-tools: Bash(git diff:*), Bash(git log:*), Bash(git status:*), Bash(git branch:*)
---

# PR作成 Skill

## コンテキスト収集

まず以下を実行して変更内容を把握する：

- 現在のブランチ: !`git branch --show-current`
- ベースブランチとの差分サマリ: !`git diff main...HEAD --stat`
- 詳細差分: !`git diff main...HEAD`
- コミット一覧: !`git log main..HEAD --oneline`

> ベースブランチが `main` でない場合（`develop` など）は、差分コマンドのブランチ名を適宜読み替える。
> `$ARGUMENTS` に追加指示がある場合はそちらを優先する。

---

## PRフォーマット

以下のMarkdown構成でPR本文を生成する。

### 概要

- レビュアーが **3分で全体を把握できる** 箇条書き（3〜5項目）
- 「何を」「なぜ」変えたかを中心に記述
- 文章は短く。冗長な説明は不要

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

## 生成方針

- **文字量は最小限**。箇条書きと図解を優先し、散文は避ける
- Mermaid図は「あると理解が速くなる」場合のみ使う。無理に入れない
- 技術スタックのリンクは公式ドキュメント・GitHubリポジトリを優先
