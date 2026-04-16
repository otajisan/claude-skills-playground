# claude-skills-playground

> コーディングエージェント（Claude Code）向けのカスタムスキルを育てるリポジトリ

## 概要

Claude Code の Skill 機能を活用し、日常の開発ワークフローを効率化するための「オレオレスキル」を集約・管理する。

## スキル一覧

| スキル | 説明 | トリガー例 |
|---|---|---|
| [pr-create](pr-create/SKILL.md) | git diff を分析し、概要・技術スタック・Mermaid 図解を含む PR 説明を自動生成する | `PRを作って` `PR作成` `プルリク` |
| [readme-sync](readme-sync/SKILL.md) | プロジェクト構造を解析して README を新規作成、または PR の変更内容に合わせて既存 README を更新する | `READMEを作って` `READMEを更新して` `readme書いて` |

## インストール

```bash
git clone https://github.com/otajisan/claude-skills-playground.git
cd claude-skills-playground
./install.sh
```

`install.sh` はリポジトリ内の各スキルディレクトリを `~/.claude/skills/` にシンボリックリンクで配置する。リポジトリ側でスキルを編集すれば即座に反映される。

## ディレクトリ構成

```
claude-skills-playground/
├── pr-create/
│   └── SKILL.md        # PR作成スキル定義
├── readme-sync/
│   └── SKILL.md        # README同期スキル定義
├── install.sh          # スキル導入スクリプト
└── README.md
```

## スキルの追加方法

1. スキル名のディレクトリを作成する
2. ディレクトリ内に `SKILL.md` を配置する
3. YAML frontmatter で `name`, `description`, `allowed-tools` を定義する
4. 本文にスキルの実行手順を Markdown で記述する
