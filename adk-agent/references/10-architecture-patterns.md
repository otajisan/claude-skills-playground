# 10 アーキテクチャ — 協調パターンと Workflow の選定

> いつ読むか: design で構成を決めるとき、scaffold でエージェント分割・配線を書くとき。
> 出典: 第 1 章 1.1.6、第 2 章（2.1〜2.4、2.8、コラム）、第 9 章 9.2（要約・再構成）

## 最初に決める 3 つ（第 2 章コラム）

1. **単一 vs マルチ** — 1 つの LLM 推論で完結し、ツールが 10 個以下なら単一。複数ドメインにまたがるならマルチ。迷ったら単一から（後からマルチ化できる）
2. **静的 vs 動的オーケストレーション** — 処理順序を固定できるなら Graph-based Workflow、コードで分岐・ループを制御するなら Dynamic Workflow、固定できないなら Collaborative Workflow / sub_agents 委譲
3. **モデルの配置** — 全エージェントで `model=` を明示（`config.AGENT_MODEL`）。分類・ルーティング・単純変換は短い Instruction とキャッシュで最適化する

## ADK v2.2.0 のレイヤー

Agent / Node 層 → Workflow 層（Graph / Dynamic / Collaborative / Template）→ Runner 層（イベント発行・リトライ・HITL 再開）→ Session 層（InMemory / Database / VertexAi）→ Artifact 層（InMemory / GCS / file://）→ Memory 層（memory:// / rag:// / agentengine://）→ Tool 層（FunctionTool / McpToolset / OpenAPI / A2A）。
設計方針は **型による安全性・合成可能性・プラグイン可能なバックエンド**（同一コードで dev / staging / prod のバックエンドを差し替える）。

v2.2.0 で可能になったこと: 実行グラフをコードで固定（決められる）、`request_input` / `rerun_on_resume` で HITL を Workflow に組み込む（止められる）、`adk test` / `eval` / `optimize` / multi-turn 評価（測れる）、AutoTracingPlugin / OpenTelemetry `gen_ai.client.*` / `custom_metadata`（見える）、`--adk_version` / `--trigger_sources` / `to_a2a(Workflow)`（つなげられる）。破壊的変更: 既定モデルが `gemini-3-flash-preview` に変わった（暗黙既定に依存しない）、`global_instruction` は非推奨（`GlobalInstructionPlugin` を使う）。

## マルチエージェント協調パターン 5 つ（第 1 章）

| パターン | 構造 | 適するタスク | ADK での実現 |
|---|---|---|---|
| マネージャー-ワーカー | 階層型 | タスク分解・委譲 | `Agent(sub_agents=[...])`。マネージャーはツールを持たず振り分けに特化 |
| 専門家合議 | 並列型 | 多角的分析 | `ParallelAgent` + 集約 Agent（`output_key` で State 受け渡し） |
| コンペティション / ディベート | 競争型 | 最適解選定 | `ParallelAgent` で候補生成 → `SequentialAgent` で評価 |
| ブラックボード | 共有型 | 非同期協調・手順が事前確定しない問題 | State + `output_key` を共有ストアとして使う |
| イベント駆動 | 分散型 | Webhook / スケジュール / 他エージェント通知 | A2A（HTTP / SSE） |

複合は普通（マネージャー-ワーカーの内部で専門家合議など）。

## Workflow パターン選定表（第 2 章 2.4.10）

| パターン | 使い所 | 利点 | 注意 |
|---|---|---|---|
| Graph-based Workflow `Workflow(edges=[("START", a, fn, b, done)])` | 固定手順・分岐・fan-out / fan-in | 実行順序が明示的で評価しやすい | Live Streaming など一部非対応 |
| Dynamic Workflow `@node` + `ctx.run_node()` | ループ・複雑な条件分岐・HITL・並列制御 | Python で分岐・ループ・再開を書ける | HITL で止まる親ノードは `@node(rerun_on_resume=True)`。決定的 ID 設計 |
| Collaborative Workflow `Agent(sub_agents=..., mode=...)` | 親から専門サブエージェントへ LLM 判断で委譲 | LLM 主導の協調 | `mode` の制約と文脈分離を理解する。Graph 内の task モードに制限あり |
| Template Workflow `SequentialAgent` / `ParallelAgent` / `LoopAgent` | 単純な順次・並列・反復、既存コード保守 | 少ない記述 | 複雑な分岐・再開・HITL は Graph / Dynamic へ |
| `BaseAgent` 継承（`_run_async_impl`） | 特殊な低レベル拡張（A/B・フォールバック・投票） | 完全な制御 | イベント発行・再開・リトライ整合の実装責任が重い。まず Dynamic で表現できないか検討 |
| HITL（`LongRunningFunctionTool` / `request_input`） | 高リスク操作・承認フロー | 安全性 | 人間待ちのレイテンシ |

判断軸マップ: 左上「Template（互換・単純定型）」から始め、構造が複雑なら右（Graph-based → 明示グラフ）、判断を動的にしたいなら下（Collaborative）、両方なら Dynamic。

### Template Workflow の設計注意

- `SequentialAgent`: 各子に `output_key` を設定し後段が State 参照。子は 3〜5 が実用範囲（レイテンシ累積）。1 つがエラーで停止
- `ParallelAgent`: 依存がある子は使わない。並列数が多いとレートリミット。子が同じ State キーに書くと競合 → `temp:flight_result` 等でキーを分離。一部失敗でも他は続行
- `LoopAgent`: **`max_iterations` を必ず設定**（無限ループ防止）。脱出は `EventActions(escalate=True)`。反復でコンテキストが蓄積するので Compaction を検討。同じ Agent インスタンスを複数の親に再利用しない
- ネストは **3 層まで**。階層がわかる命名（トレース追跡）。ネスト内は同じ State を共有するので `output_key` 衝突に注意

### sub_agents 委譲の注意

`description` が LLM の委譲判断の入力。誤ルーティング・2 段推論のコスト増を、詳細な description・短いルート Instruction・`disallow_transfer_to_peers=True` で軽減。親へ戻すのを禁じるなら `disallow_transfer_to_parent=True`。

`mode`: `chat`（既定。対話型委譲）/ `task`（必要な確認だけしてから親へ戻る）/ `single_turn`（ユーザーと直接やり取りせず 1 ターンで結果を返す）。

### sub_agents vs AgentTool

| 項目 | sub_agents | AgentTool |
|---|---|---|
| 制御 | LLM が transfer | ツールとして call |
| セッション | 共有 | 独立コンテキスト |
| 戻り先 | サブエージェントが持つ | 呼び出し元に結果 |
| 用途 | 対話型の委譲 | 特定タスクの実行依頼。親が途中結果を受けて次を呼ぶとき |

## Agent（LlmAgent）コアパラメータ

- 識別: `name`（一意）/ `model`（明示）/ `description`（委譲判断に使う）
- 振る舞い: `instruction`（str or `ReadonlyContext -> str`）/ `static_instruction`（キャッシュ最適化）/ `tools` / `sub_agents` / `input_schema` / `mode` / `include_contents`
- 出力: `output_key`（State へ自動保存）/ `output_schema`（Pydantic。JSON 限定・フラット推奨・`output_key` と併用可）/ `generate_content_config`（temperature: 事実・コード 0.0〜0.3、汎用 0.5〜0.7、創作 0.8〜1.0）/ `planner` / `code_executor` / `retry_config` / `timeout` / `disallow_transfer_to_*`
- コールバック: `before/after_agent`、`before/after_model`（`callback_context`, `llm_request|llm_response`）、`on_model_error`、`before/after_tool`（`tool`, `args`, `tool_context`[, `tool_response`]）、`on_tool_error`。**引数名は変えない**

## ディレクトリ構成（規模が大きくなったら）

```
my_agent/
├── __init__.py      # from . import agent as agent; from .agent import root_agent
├── agent.py         # 組み立てのみ
├── agents/          # サブエージェント
├── tools/           # ツール
├── schemas/         # Pydantic 出力スキーマ
├── prompts/         # Instruction テンプレート
├── .env / requirements.txt
```

複数エージェントプロジェクトは親ディレクトリを `adk web <parent>` に渡すと UI で切り替えられる。Root が `SequentialAgent` 等（LlmAgent 以外）や動的 Instruction の場合、`adk web` のエージェント情報表示（`/apps/{app}/app-info`）が失敗することがある → 動作確認は `adk run ... --jsonl` を主経路にする。

## 関連アンチパターン

God Agent（ツール 10 個超・巨大 Instruction → 責務分割 + ルーター）、Chatty Agents（1 タスク 3 往復超 → 必要情報を 1 回の引き渡しにまとめる。疎結合は通信回数を増やすことではない）、Monolith Deployment（トラフィック特性が違うエージェントは独立デプロイ）、Blind Delegation（サブエージェントの結果を検証ステップなしで使わない）。詳細は `90-antipatterns.md`。
