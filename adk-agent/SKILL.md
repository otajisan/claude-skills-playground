---
name: adk-agent
description: Google ADK（Agent Development Kit）でエージェント／マルチエージェントを設計・実装・評価・堅牢化・レビュー・デプロイする。『現場で役立つマルチエージェントAI設計入門（A2A × ADK）』の 3 軸体系（Context / Memory / Harness）・設計原則 10・アンチパターン 12・レビューチェックリスト 29 項目を Agentic Coding で実践する。「ADK」「Google ADK」「エージェントを設計して」「マルチエージェント設計」「A2A」「McpToolset」「adk eval」「評価セット」「ガードレール」「HITL」「Kill Switch」「Agent Engine にデプロイ」「エージェントの設計レビュー」などと言われたら必ずこのSkillを使う。引数は `<mode> [対象パス | 要件]`（mode: design / scaffold / eval / harden / review / deploy）。
allowed-tools: Bash(adk:*), Bash(python:*), Bash(python3:*), Bash(pytest:*), Bash(pip:*), Bash(uv:*), Bash(gcloud:*), Bash(git:*), Bash(find:*), Bash(grep:*), Bash(ls:*), Bash(cat:*), Bash(mkdir:*), Bash(cp:*), Read, Write, Edit, Grep, Glob
---

# ADK Agent Skill

Google ADK（Python、v2.2.x 前提）で **PoC 80 点のエージェントを本番 90 点へ届かせる** ための設計・実装・評価・堅牢化・レビュー・デプロイを、書籍の Agentic Coding 形式で進める。
Claude Code は書籍の「AI コーディングエージェント」役であり、**生成したコードを書籍のレビューポイントで自己検査してから提示する**。

**引数**: `<mode> [対象パス | 要件テキスト]`（今回の入力: `$ARGUMENTS`）。mode 省略時は Step 0 で判定する。

知識は `references/` に分割している。**SKILL.md だけで判断せず、各モードの「読む references」を Read してから作業する**（書籍の Progressive Disclosure と同じ運用）。テンプレートは `templates/` にある。パスはこの SKILL.md からの相対パス。

---

## Step 0: モード判定

| 入力 / 文脈 | モード | 目的 |
|---|---|---|
| 要件テキスト・Issue・「設計して」 | **design** | 設計判断を固めて設計ドキュメントを出す |
| design 済み or 「作って」「雛形」「scaffold」 | **scaffold** | テンプレートからプロジェクトを生成し自己レビュー |
| 「評価」「eval」「評価セット」「品質を測る」 | **eval** | 評価セット作成 → `adk eval` → 分析 → 改善 |
| 「ガードレール」「HITL」「セキュリティ強化」「Kill Switch」 | **harden** | 5 層防御・承認フロー・監査ログの追加 |
| 「レビュー」「チェックリスト」「設計の問題を見て」 | **review** | 29 項目チェックリストで判定・改善提案 |
| 「デプロイ」「Agent Engine」「Cloud Run」「運用」「監視」 | **deploy** | デプロイ先選定・手順・監視設計（実行はユーザー承認後） |

曖昧なら **1 問だけ** 聞く。判定したモードを 1 行で宣言してから Step 1 へ。

---

## Step 1: 環境確認（全モード共通）

```
ADK バージョン : !`adk --version 2>/dev/null || echo "adk コマンドなし"`
Python         : !`python3 --version`
ADK プロジェクト: !`find . -maxdepth 3 -name agent.py -not -path '*/.venv/*' -not -path '*/node_modules/*' 2>/dev/null`
モデル経路     : !`env | grep -E '^(GOOGLE_API_KEY|GOOGLE_GENAI_USE_VERTEXAI|GOOGLE_CLOUD_PROJECT|GOOGLE_CLOUD_LOCATION|AGENT_MODEL|ANTHROPIC_API_KEY)=' | sed -E 's/=(.{4}).*/=\1…/'`
```

- ADK が **2.2.x 以外**（または未インストール）なら「テンプレートと references は ADK v2.2.0 で検証。Workflow Runtime / `Context` エイリアス / `EventsCompactionConfig` などは 2.x 前提。差分は `adk --help` と公式リリースノートで確認する」と警告してから進む
- `GOOGLE_GENAI_USE_VERTEXAI=TRUE` とプレースホルダの `GOOGLE_CLOUD_PROJECT` が同居していると API キー経路でも Vertex AI に接続して `PERMISSION_DENIED` になる（`references/adk-cli.md`）。動作確認前に必ず指摘する
- 課金が発生する操作（Vertex AI / Agent Engine / Memory Bank / RAG Engine / Claude API）は **提示のみで実行しない**。ユーザーが明示的に承認した場合だけ実行する

---

## モード別手順

### design — 設計ドキュメントを作る

**読む**: `references/00-principles.md`, `10-architecture-patterns.md`, `20-context-engineering.md`, `30-memory-engineering.md`, `41-harness-guardrails-hitl.md`, `models.md`。デプロイ先まで決める場合は `70-deploy-agentops.md`。

1. 要件を **ゴール / 対象範囲 / 成功基準 / 制約 / 高リスク操作** に分解する（不足はまとめて 1 回で質問）
2. **最初に決める 3 つ** を確定する（第 2 章コラム）
   1. 単一エージェント vs マルチエージェント（1 LLM 推論で完結し、ツール 10 個以下なら単一。迷ったら単一）
   2. 静的（Graph-based Workflow）vs コード制御（Dynamic Workflow）vs LLM 判断（Collaborative / sub_agents）
   3. モデル配置（既定 `AGENT_MODEL=gemini-3.5-flash`、全エージェントで明示。Claude を使うなら `models.md` の課金・非対応機能を確認）
3. 3 軸を設計する: Context（Instruction 4 要素 × 3 スコープ、コールバック、Agent Skills）／ Memory（Session / State キー / Compaction / Memory Bank / RAG）／ Harness（評価計画、ガードレール、HITL 承認ポイント）
4. 出力は次のフォーマット。**設計判断には理由を 1 行添える**

```markdown
# <エージェント名> 設計ドキュメント

## 1. 要件サマリ（ゴール / 範囲 / 成功基準 / 制約 / 高リスク操作）
## 2. 最初に決める 3 つ
| 判断 | 選択 | 理由 |
## 3. アーキテクチャ
（Mermaid: エージェント構成と State の流れ）
| エージェント | 責務（1〜2 文） | model | tools | output_key | mode |
## 4. Context Engineering（Instruction 方針・コールバック・Agent Skills）
## 5. Memory Engineering
| State キー | スコープ | 寿命 | 用途 |
SessionService / Compaction（interval / overlap）/ Memory Bank・RAG の採否
## 6. Harness Engineering
| ツール | リスク | 可逆性 | 承認要否（HITL） | 権限（ロール） |
評価計画: 6 カテゴリ × 件数、必須メトリクスと閾値
## 7. ツール・外部接続（FunctionTool / MCP / CLI / A2A の選定理由）
## 8. デプロイ先とコストの観点（Agent Engine / Cloud Run / GKE、課金ポイント）
## 9. 未決事項・リスク
## 次のステップ → `/adk-agent scaffold`
```

### scaffold — プロジェクトを生成し自己レビューする

**読む**: `references/10-architecture-patterns.md`, `20-context-engineering.md`, `30-memory-engineering.md`, `50-tools-mcp-cli.md`, `adk-cli.md`, `models.md`。A2A 構成なら `60-a2a.md`。

1. design ドキュメント（無ければ design モードを先に実施）からエージェント一覧・State キー・ツール・HITL 条件を取り出す
2. `templates/agent_package/` をコピーして要件に合わせて書き換える。**構造は `adk create` 準拠**（`__init__.py` が `agent` サブモジュールと `root_agent` を公開）。規模が大きければ `agents/` `tools/` `schemas/` に分割し `agent.py` は組み立て専用にする
3. 必ず同梱する: `config.py`（`AGENT_MODEL` 等を環境変数から）、`state_keys.py`、`callbacks.py`（合成済み）、`session_config.py`、`.env.example`、`requirements.txt`、`eval/eval_set.json`（最低 5 件）、`eval/eval_config.json`、`tests/`。`.gitignore` に `.env` を追加する
4. 生成後に **セルフレビュー**（下記チェック表）を実施し、結果を報告に含める
5. 動作確認手順を提示: `adk run <pkg> "<入力例>" --jsonl` → `pytest tests/` → `adk eval <pkg> eval/eval_set.json --config_file_path eval/eval_config.json`（API キー必要。実行はユーザーに委ねる）

**セルフレビュー表（書籍 RP1〜6 + 表 2.8〜2.11）**

| 観点 | 確認 |
|---|---|
| エージェント | `root_agent` 変数名 / `name` 一意 / `description` 具体的（sub_agents 委譲に使う）/ `model` を全エージェントで明示 / `output_key` 衝突なし / 動的 Instruction は `ReadonlyContext` |
| ツール | 型ヒント / docstring 1 行目 + Args の具体例 / エラーは `{"status": "error", ...}` dict で返す（raise しない）/ 冪等 / 1 ツール 1 責務 / 10 個以下 |
| コールバック | 引数名 `callback_context` `tool_context` を変えない / None で続行・値で差し替えの規約 / 合成順（レート制限 → 注入） |
| スキーマ | Pydantic `Field(description=)` / ネスト 3 層以内 / Optional は省略可能な引数のみ |
| セキュリティ | シークレット直書きなし / `.env` を `.gitignore` / ユーザー入力を SQL・コマンドに直接渡さない / 外部レスポンスの検証 |
| 設定 | モデル・URI・閾値がコードに直書きされていない（Config Drift 対策） |

### eval — 評価駆動で改善する

**読む**: `references/40-harness-eval.md`, `adk-cli.md`。

1. 評価セットが無ければ `templates/eval/` から作る。**6 カテゴリ**（正常系 / ツール選択 / エラーハンドリング / マルチターン / エッジケース / 安全性）を最低 1 件ずつ、開発時 5 件以上・本番前 30 件以上
2. `eval_config.json` の閾値は段階制: dev 0.6 / 0.5 / 3.0 → staging 中間 → prod 0.9 / 0.8 / 4.0（tool_trajectory / response_match / response_evaluation）
3. `adk eval <agent_dir> eval/eval_set.json --config_file_path eval/eval_config.json --print_detailed_results` を実行（API キーが無ければコマンド提示のみ）
4. 結果分析 → 改善アクション（`40-harness-eval.md` の判断フロー）: trajectory 低下 → Instruction / tool description、match 低下 → `final_response` の書き方 / カスタムメトリクス、ばらつき → 複数回実行。改善サイクルは **最低 2 回**
5. 発見した失敗事例は評価セットに追加し、CI 組み込み（`templates/ci/agent-eval.yml` + `check_eval_thresholds.py`）を提案する

### harden — 5 層防御と HITL を組み込む

**読む**: `references/41-harness-guardrails-hitl.md`, `80-security.md`, `20-context-engineering.md`。

1. 対象エージェントのツールを **リスク × 可逆性** で分類し、承認基準 6 つ（影響範囲 / 可逆性 / 金額 / 権限 / 法的リスク / 前例）で HITL 対象を決める
2. 5 層を配置する: L1 `before_model_callback`（インジェクション検出・レート制限・Kill Switch・エスカレーション判定）→ L2 Instruction のセキュリティルール → L3 `before_tool_callback`（RBAC・引数検証・実行回数制限・HITL 承認）→ L4 `after_tool_callback`（間接インジェクション検出・PII マスク）→ L5 `after_model_callback`（機密情報マスク）。全層で監査ログ
3. `templates/harden/` の `kill_switch.py` / `escalation.py` / `execution_limiter.py` / `audit_logger.py` を取り込み、`callbacks.py` の合成に組み込む
4. ガードレール自体の pytest（正常通過 / 検出の両方）を追加する。ガードレール内の例外は **安全側に倒す**（try/except でブロック応答）
5. 新規エージェントは **自律レベル 0（FULL_HITL）** から始め、承認率 95% 超で段階的に上げる方針を報告に書く

### review — 設計レビューを行う

**読む**: `references/91-review-checklist.md`, `90-antipatterns.md`, `80-security.md`。

1. 対象ソースを Read / Grep で解析する（Agent 定義、tools 数、Instruction 長、コールバックの有無、model 指定、シークレット、SessionService、max_iterations、評価セットの存在）
2. 29 項目（A-1〜A-6 / S-1〜S-8 / O-1〜O-5 / C-1〜C-5 / Q-1〜Q-5）を **適合 / 要改善 / 未対応** で判定し、該当アンチパターン名を添える
3. **S 項目はゲート**: 1 つでも未対応なら「差し戻し（本番投入不可）」。他観点は要改善 3 項目以内で条件付き可
4. `templates/review/design-review-report.md` のフォーマットで出力し、改善提案は **優先度順・コード例付き**。`/review-apply` にそのまま渡せる粒度にする

### deploy — デプロイと運用設計

**読む**: `references/70-deploy-agentops.md`, `80-security.md`, `adk-cli.md`。

1. デプロイ先を選定フローで決める（ADK 前提 → GPU 不要 → 運用チーム小規模なら Agent Engine。カスタムドメイン / ゼロスケールなら Cloud Run、複雑なネットワーク / GPU なら GKE）
2. デプロイ前チェックリスト（表 8.4 相当）を確認する: ローカル動作 / `root_agent` 公開 / `requirements.txt` / シークレットは Secret Manager / IAM / リージョン / `adk eval` 合格 / Git コミット済み
3. `adk deploy agent_engine ./<pkg> --project <P> --region <R> --otel_to_cloud` などのコマンドと必要 IAM を **提示**する。実行はユーザー承認後
4. 運用設計を出す: SLI/SLO 基本セット、アラート 3 層、コスト監視メトリクス、障害パターン 6 つへの備え、CI/CD（pytest → eval → deploy）

---

## 共通方針

- **モデルは設定で差し替える**: 全 Agent の `model=` は `config.py` 経由。暗黙既定（`gemini-3-flash-preview`）に依存しない。Claude をランタイムに使う提案をする前に `references/models.md` を読み、課金（Claude Code のサブスクは API 利用をカバーしない）と非対応機能（`google_search` / `BuiltInCodeExecutor` / ADK Context Caching は Gemini 限定）を明示する
- **評価駆動**: コードより先に評価セット。品質は `adk eval` で測り、「手で試して動いた」を根拠にしない
- **セキュリティは後付けしない**: scaffold 時点で `.env` 除外、`os.environ` / Secret Manager、ツール権限テーブルの骨格を置く
- **設計原則 10 の判断基準**（`00-principles.md`）を設計・レビューの根拠として引用する。数値目安: Instruction 500 トークン超で外部化、ツール 5 個超で分割検討・10 個超で分割推奨、ネスト 3 層まで、評価ケース本番前 30 件
- **単一責任**: Instruction を 1〜2 文で説明できないエージェントは分割する
- **コメント・ドキュメントは日本語**。Python 3.11+、型ヒント必須
- 書籍の API 名（`Agent` / `Workflow` / `@node` / `Context` / `McpToolset` / `to_a2a` / `RemoteA2aAgent` / `EventsCompactionConfig`）は ADK v2.2.0 のもの。実環境と食い違ったら `adk --help` と `google.adk` のソースを正とする
- 各モードの最後に **次のステップ** を示す: design → scaffold → eval → harden → review → deploy。レビュー指摘の反映は `/review-apply`、PR は `/pr-create`
- 引数が空でプロジェクトも無い場合は「何を作りたいか（業務・入力・出力・高リスク操作）」を聞いて design から始める
