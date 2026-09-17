# claude-skills-playground

> コーディングエージェント（Claude Code）向けのカスタムスキルを育てるリポジトリ

## 概要

Claude Code の Skill 機能を活用し、日常の開発ワークフローを効率化するための「オレオレスキル」を集約・管理する。

## スキル一覧

| スキル | 説明 | トリガー例 |
|---|---|---|
| [pr-create](pr-create/SKILL.md) | git diff を分析して概要・技術スタック・Mermaid 図解を含む PR 説明を生成し、ラベル / Assignee / Project / マイルストーン / 関連 Issue まで埋めて PR を作成する | `PRを作って` `PR作成` `プルリク` |
| [readme-sync](readme-sync/SKILL.md) | プロジェクト構造を解析して README を新規作成、または PR の変更内容に合わせて既存 README を更新する | `READMEを作って` `READMEを更新して` `readme書いて` |
| [refinement](refinement/SKILL.md) | GitHub Issue をコードベースとすりあわせて実装プランをドラフトし、Issue 本文に追記する。ラベル / Assignee / Project / マイルストーン / Issue Type の欠けも補完する | `refinement` `Issueを整理して` `実装プランを立てて` |
| [review-apply](review-apply/SKILL.md) | レビュー指摘（Remote PR / 貼り付け / 会話 / セルフ）を分類して反映し、Remote PR なら各コメントに返信する | `レビューに対応して` `指摘を反映して` `セルフレビュー` |
| [adk-agent](adk-agent/SKILL.md) | Google ADK のエージェント / マルチエージェントを設計・実装・評価・堅牢化・レビュー・デプロイする。書籍『現場で役立つマルチエージェントAI設計入門（A2A × ADK）』の 3 軸体系・設計原則 10・アンチパターン 12・レビューチェックリスト 29 項目を Agentic Coding で実践。6 モード（design / scaffold / eval / harden / review / deploy）+ `references/`（段階的読み込み）+ `templates/`（ADK v2.2.0 準拠の骨格） | `ADK でエージェントを設計して` `/adk-agent review ./my_agent` `adk eval の評価セットを作って` |

## フック一覧

| フック | イベント | 説明 |
|---|---|---|
| [workflow-reminder](hooks/workflow-reminder.sh) | `Stop` | git 状態に応じて実装完了ワークフローを 2 段階で誘導する。**①** ベースブランチ上に変更があれば作業ブランチの作成を促す。**②** フィーチャーブランチにコミットがあるのに PR 未作成なら「レビュー→修正ループ（`/code-review` → `/codex:review` → セキュリティレビュー → `/review-apply`）→ `/readme-sync` → `/pr-create`」を促す |

## インストール

```bash
git clone https://github.com/otajisan/claude-skills-playground.git
cd claude-skills-playground
./install.sh
```

`install.sh` は以下を一括で行う:

1. **skills**: `*/SKILL.md` を持つディレクトリを `~/.claude/skills/` にシンボリックリンクで配置
2. **hooks (scripts)**: `hooks/*.sh` を `~/.claude/hooks/` にシンボリックリンクで配置
3. **hooks (settings.json)**: `hooks/hooks.json` の定義を `~/.claude/settings.json` に `jq` で冪等マージ（既存設定・他のフックは保持、`command` の重複は自動スキップ）

いずれもシンボリックリンクなので、リポジトリ側を編集すれば即座に反映される。既存ファイルを置き換える場合は `.backups/` にタイムスタンプ付きで退避する。

> `jq` が必要です (`brew install jq`)。未インストールの場合、skills / hooks scripts の配置までは行い、settings.json のマージはスキップされます。

## ディレクトリ構成

```
claude-skills-playground/
├── pr-create/
│   └── SKILL.md            # PR作成スキル定義
├── readme-sync/
│   └── SKILL.md            # README同期スキル定義
├── refinement/
│   └── SKILL.md            # Issue refinement スキル定義
├── review-apply/
│   └── SKILL.md            # レビュー反映スキル定義
├── adk-agent/
│   ├── SKILL.md            # ADK エージェント設計スキル（モードルーター）
│   ├── references/         # 設計ガイド 14 本（原則 / アーキ / Context / Memory / 評価 / ガードレール / ツール / A2A / デプロイ / セキュリティ / アンチパターン / チェックリスト / モデル / CLI）
│   └── templates/          # agent_package / eval / tests / harden / a2a / skills / ci / review の骨格
├── hooks/
│   ├── hooks.json          # settings.json にマージするフック定義
│   └── workflow-reminder.sh
├── install.sh              # skills / hooks 一括導入スクリプト
└── README.md
```

## スキルの追加方法

1. スキル名のディレクトリを作成する
2. ディレクトリ内に `SKILL.md` を配置する
3. YAML frontmatter で `name`, `description`, `allowed-tools` を定義する
4. 本文にスキルの実行手順を Markdown で記述する
5. 知識量が多いスキルは `references/`（必要時に Read する詳細ガイド）と `templates/`（生成物の骨格）に分け、`SKILL.md` は判定と手順のルーターに留める（`adk-agent` を参照）

## フックの追加方法

1. `hooks/` にスクリプト（`*.sh`）を置く
2. `hooks/hooks.json` に当該イベントへのエントリを追記する
   ```json
   {
     "Stop": [
       { "type": "command", "command": "bash ~/.claude/hooks/your-hook.sh", "timeout": 10 }
     ]
   }
   ```
3. `./install.sh` を再実行する（既に登録済みのものはスキップされる）
