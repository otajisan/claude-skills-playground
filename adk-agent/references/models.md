# models — ランタイム LLM の差し替え（Gemini / Claude）

> いつ読むか: design の「モデル配置」、scaffold の `config.py`、Claude をランタイムに提案する前（必読）。
> 出典: 書籍「サンプルコードと動作環境」、第 2 章 2.2.1、第 8 章 8.5（コラム含む）、Anthropic `claude-api` スキルの価格表（2026-06 時点キャッシュ）

## 方針

- **モデルはコードに直書きせず `config.AGENT_MODEL`（環境変数）で差し替える**（Config Drift 対策）。全 Agent で `model=` を明示し、ADK の暗黙既定（v2.2.0 は `gemini-3-flash-preview`）に依存しない
- **ローカル開発の既定は `gemini-3.5-flash`**。書籍の検証モデルであり、Gemini Developer API（`GOOGLE_API_KEY` + `GOOGLE_GENAI_USE_VERTEXAI=FALSE`）にはレート制限付きの無料枠がある（最新条件は ai.google.dev の pricing で確認）
- Claude をランタイムに使うのは **追加課金を許容し、Gemini 限定機能を使わない** と判断した場合。提案時は必ず下表の課金・非対応を明示する
- 3 系と 2 系の混在は避ける（ツール呼び出し・JSON スキーマ解釈が異なる）。Compaction の summarizer・LLM-as-judge も同系で揃える

## 経路と課金

| 経路 | 設定 | 課金 | 備考 |
|---|---|---|---|
| Gemini Developer API | `GOOGLE_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI=FALSE`, `model="gemini-3.5-flash"` | 無料枠あり（レート制限）。有料 Standard は入力 $1.50 / 出力 $9.00 per 1M tokens（書籍時点） | ローカル・PoC の既定。`.env` に Vertex 用プレースホルダが残ると Vertex に接続して `PERMISSION_DENIED` |
| Gemini on Vertex AI | `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, ADC | 有料（$300 トライアルのみ無料） | 本番経路。Memory Bank / RAG Engine / Agent Engine も従量課金 |
| Claude via Anthropic API | `ANTHROPIC_API_KEY`, `AGENT_MODEL=anthropic/<model-id>`（`AnthropicLlm` または `LiteLlm`） | **有料**。Opus 5 $5 / $25、Sonnet 5 $2 / $10、Haiku 4.5 $1 / $5 per 1M tokens | **Claude Code のサブスクリプション（Pro / Max）は API 利用をカバーしない**。別会計 |
| Claude on Vertex AI | ADC + `GOOGLE_CLOUD_PROJECT` / `LOCATION`、`AGENT_MODEL=vertex-anthropic/<model-id>`（`Claude` クラス） | **有料**（パートナー価格、Google Cloud に請求） | ADK 経由の Context Caching は使えない（書籍 8.5.5 注記）|

モデル ID（Anthropic API）: `claude-opus-5` / `claude-sonnet-5` / `claude-haiku-4-5`。日付サフィックスを付けない。Vertex は同じ ID をプレフィックスなしで使う（旧スナップショットは `@` 区切り）。

## ADK での接続コード（v2.2.0 で確認済み）

| 経路 | クラス（`google.adk.models.anthropic_llm`） | 認証 | 追加パッケージ |
|---|---|---|---|
| Anthropic API 直 | `AnthropicLlm(model="claude-sonnet-5", max_tokens=8192)` | `ANTHROPIC_API_KEY`（`AsyncAnthropic()` 既定） | `pip install "google-adk[extensions]"`（`anthropic>=0.78`） |
| Claude on Vertex AI | `Claude(model="claude-sonnet-5")` | `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION` + ADC（`AsyncAnthropicVertex`） | 同上 |
| LiteLLM | `google.adk.models.lite_llm.LiteLlm(model="anthropic/claude-sonnet-5")` | provider ごと | `google-adk[extensions]`（litellm） |

注意:
- **文字列 `"claude-..."` をそのまま `Agent(model=)` に渡すと、ADK のレジストリは Vertex AI 経路（`Claude`）に解決する**。経路を明示するには BaseLlm インスタンスを渡す
- レジストリの対応パターンは `claude-3-.*` / `claude-.*-4.*`（例: `claude-sonnet-5` は文字列指定では解決されない）。インスタンス指定なら任意のモデル ID を使える
- `templates/agent_package/config.py` の `build_model()` は `anthropic/` → `AnthropicLlm`、`vertex-anthropic/` → `Claude`、`litellm/` → `LiteLlm`、それ以外 → 文字列（Gemini）に振り分ける。`.env` の `AGENT_MODEL` を変えるだけで切り替わる

## 機能対応マトリクス（Claude をランタイムにするときの制約）

| 機能 | Gemini | Claude（LiteLLM / Vertex） | 代替 |
|---|---|---|---|
| `google_search` 組み込みツール | ○ | × | RAG Engine、独自 Web 検索 FunctionTool / MCP |
| `BuiltInCodeExecutor`（`code_executor=`） | ○ | × | サンドボックス化した CLI ツール、外部実行サービス |
| ADK 経由の Context Caching（`types.CachedContent`） | ○ | ×（8.5.5） | Compaction、Instruction 短縮。Anthropic 側のプロンプトキャッシュを ADK から使えるかは実装依存 → 実測 |
| `output_schema`（構造化出力） | ○ | ○（モデル側の JSON 準拠に依存。フラットに） | — |
| FunctionTool / McpToolset / A2A | ○ | ○ | — |
| `EventsCompactionConfig` の summarizer | ○ | ○（`LlmEventSummarizer(llm=<BaseLlm>)` に渡す） | — |
| `adk eval` の `response_evaluation_score`（Vertex AI Evaluation） | ○ | ○（評価側は Vertex AI、対象モデルは不問） | — |

## モデル選定の判断基準（第 1 章 1.1.7・第 8 章 8.5.2）

コスト・レイテンシ・推論能力のトレードオフを **評価結果（adk eval）で判断**する。差し替えたら評価セットと主要ハンズオンを再実行する。タスク別: ルーティング / 分類は短い Instruction、FAQ はキャッシュ、抽出 / 要約は出力スキーマ、複雑推論は評価セット、コード生成はテスト実行、創作は人手レビュー。モデル ID・料金・レイテンシは変わるので、運用前に公式 pricing で再計算する。

## 提案テンプレ（ユーザーに示す文言）

> ランタイムを Claude にすると Anthropic API（または Vertex AI）の従量課金が発生します（Claude Code のサブスクは対象外）。また `google_search` / `BuiltInCodeExecutor` / ADK Context Caching は使えません。無料枠で進めるなら `AGENT_MODEL=gemini-3.5-flash` を推奨します。切り替える場合は `.env` の `AGENT_MODEL` と API キーを変えるだけで、コード変更は不要です。
