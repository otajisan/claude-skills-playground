# 30 Memory Engineering — 何を覚え、何を忘れるか

> いつ読むか: design で State / Session / Memory / RAG を決めるとき、scaffold で `state_keys.py` `session_config.py` `App` を書くとき。
> 出典: 第 4 章（要約・再構成）

## 三層モデル

| 層 | 寿命 | スコープ | アクセス |
|---|---|---|---|
| Session | 対話単位（生成〜削除） | 1 ユーザー × 1 エージェント。会話履歴（イベント列）・State・メタデータ | `SessionService`（create / get / list / delete） |
| State | プレフィックスで異なる | Key-Value | `session.state["key"]` / `tool_context.state` |
| Memory | 永続 | ユーザー / グローバル。対話から抽出・構造化された事実・嗜好 | `MemoryService`（Memory Bank / InMemory） |

Session は生ログ、Memory は抽出・統合された知識。Session の粒度はユースケースで決める（チャットなら 1 チャット、タスク実行なら 1 タスク、常駐なら 1 日）。細かすぎると文脈を失い、粗すぎると Compaction 頻度が上がる。

Memory への取り込みと検索は自動ではない: `after_agent_callback` で `await callback_context.add_session_to_memory()`、参照は `PreloadMemoryTool()`（毎ターン先読み）/ `LoadMemoryTool`（必要時に検索）/ `callback_context.search_memory(query)`。Runner に `memory_service=` を渡す。

## SessionService の選定

| | InMemorySessionService | DatabaseSessionService | VertexAiSessionService |
|---|---|---|---|
| 永続化 | プロセス終了で消失 | RDB（PostgreSQL / MySQL / SQLite）。`sessions` `events` テーブル自動作成 | Vertex AI マネージド（Agent Engine ID にひも付く） |
| 用途 | ローカル開発・pytest | オンプレ / マルチクラウド / 既存 RDB 共有 / SQL 分析 | Google Cloud 本番・Agent Engine |
| 接続 | なし | `postgresql+asyncpg://...` / `sqlite+aiosqlite:///...`（Cloud SQL は Auth Proxy 経由 localhost） | `project` / `location` / `agent_engine_id` |

選定フロー: Google Cloud で運用？ No → 既存 RDB を共有？ Yes → Database / No → InMemory（PoC）。Yes → Agent Engine にデプロイ？ Yes → VertexAi / No → Database。

切り替えは `create_session_service()` で `AGENT_ENV`（dev / staging / prod）から 1 行で行う。必須環境変数が無ければ `ValueError` で明確に落とす。

> 現場の教訓（BLUEISH コラム）: SessionService 実装ごとにシリアライズ・サイズ制限が異なる。InMemory で確認しただけでリリースせず、**本番想定の SessionService でファイル添付まで通してから** リリースする。

## State 設計

| プレフィックス | スコープ | 寿命 | 用途 |
|---|---|---|---|
| `app:` | アプリ全体 | 永続化バックエンド存続中 | 設定・バージョン・機能フラグ |
| `user:` | 同一ユーザーの全 Session | 同上 | 名前・権限・嗜好 |
| なし | 現在の Session | Session 存続中 | 対話の作業状態 |
| `temp:` | 現在の Invocation | 1 回の実行 | 中間結果・一時フラグ |

- 実務では **プレフィックスを必ず付ける**（デバッグ時に寿命が判断できる）
- `temp:` は次の Invocation で消える前提。残したい値は `user:` か Memory へ
- 型安全: `StateKeys` 定数クラス + アクセサ（`get_user_tier` は許可値以外を既定に丸める）、または Pydantic `UserState`（`load_user_state` / `save_user_state`）
- `output_key` で State 連携（`output_key="temp:analysis_result"` のようにプレフィックス付きも可）
- `ParallelAgent` の子は書き込みキーを分ける

**アンチパターン**: State の肥大化（数百件の注文 → ID 上位 10 件だけ保存し必要時に API）／スコープ誤用（一時値を `user:` に）／機密情報の保存（トークン・API キーは State に置かない。State はログ・UI に出る）。

## Compaction（会話履歴の圧縮）

`App(events_compaction_config=EventsCompactionConfig(...))` で設定し、**`Runner(app=app, ...)` で渡す**（`agent=` 直接渡しだと無視される）。`adk run` / `adk web` ではパッケージ `__init__.py` から `app` を公開する（ローダーは `app` → `root_agent` の順に探し、`root_agent` だけだと App 設定は捨てられる。v2.2.0 の `AgentLoader` で確認）。v2.2.0 時点で experimental warning あり。post-invocation 方式（応答後にバックグラウンドで要約）。pending function call 中は自動抑制。

| パラメータ | 意味 |
|---|---|
| `compaction_interval` | 未圧縮 invocation がこの数に達したら発火（必須） |
| `overlap_size` | 文脈連続性のため要約後も生で残す直前 invocation 数（必須） |
| `token_threshold` + `event_retention_size` | 直近プロンプトのトークン数で発火（OR 条件）。ツール出力が可変長・RAG が大きいチャンクを返すときに併用 |
| `summarizer` | `LlmEventSummarizer(llm=<BaseLlm>)`。未指定なら Agent のモデル。別モデルにできる |

推奨値（summarizer は既定モデル）:

| ユースケース | interval / overlap |
|---|---|
| チャットボット（短い対話） | 10 / 1 |
| カスタマーサポート | 20 / 2 |
| リサーチ（長時間・文脈連続） | 30 / 3 |
| コード生成（大量コード） | 50 / 5 |
| タスク実行（中間結果保持） | 30 / 2 |

トレードオフ: interval 小 = コスト・レイテンシ低、情報損失リスク高。失いたくない値は `tool_context.state["user:important_context"]` のように **Compaction 対象外の State に明示保存**。Compaction 前後の応答品質は `adk eval` で検証する。効果の例: 20 ターンで合計トークン約 53% 削減。

Compaction（Session 内履歴の圧縮）と Consolidation（Memory Bank 内の記憶統合）は別物。

## Vertex AI Memory Bank

- 記憶の抽出・意味検索・Consolidation（重複統合・矛盾解決・不要記憶除去）・スコープ管理（ユーザー / グローバル）
- 保存モード: **GenerateMemories**（抽出 + 既存と統合。既定）/ CreateMemory（統合なし。住所変更履歴や監査など変更経過を残したいときだけ）
- Instruction で記憶方針を書くと品質が上がる（「製品の使用状況・技術レベル・嗜好を覚える」「一時的な話題は記憶しない」「**個人情報は記憶しない**」）
- PII を保存するなら個人情報保護法 / GDPR（同意・削除請求対応）を検討。保存前バリデーションを推奨
- CLI 配線: `--memory_service_uri="agentengine://projects/P/locations/R/reasoningEngines/ID"`（ローカルは `memory://`）。事前に Vertex AI 側でリソース作成が必要、**有料**

## Vertex AI RAG Engine

| | RAG Engine | Memory Bank |
|---|---|---|
| 情報 | 静的知識（マニュアル・FAQ・規定） | 動的記憶（対話から学んだ事実・嗜好） |
| ソース | 事前登録コーパス | 過去 Session |
| 更新頻度 | 月次〜四半期 | 日次〜対話ごと |
| 一言 | 組織の知識 | 個人の記憶 |

`VertexAiRagRetrieval(name, description（いつ使うか）, rag_corpora=[...], similarity_top_k=5, vector_distance_threshold=0.5)` をツールとして装備。コーパス ID は環境変数から。コーパスは情報種別ごとに分離（product / faq 0.4 / policy 0.3 のように閾値も別）。

制約と対策: チャンク境界の断裂 → `chunk_overlap`（512 トークンなら 100〜150、20〜30%）／最新情報の遅延 → 在庫・価格は API ツール、RAG は変更頻度の低い知識／多言語 → 言語別コーパス。`google_search` は公開 Web・リアルタイム、RAG は自社文書・機密可。

## 情報源の選定フロー

ユーザー固有の情報？ Yes → Memory Bank（Preload / Load / search_memory）。No → リアルタイムデータ？ Yes → API ツール（在庫・価格・配送）。No → 組織の公式知識？ Yes → RAG Engine。No → 公開情報？ → `google_search`。

併用パターン: ①ツール分離型（RAG ツール + PreloadMemoryTool。根拠追跡しやすい。まずこれ）→ ②コールバック統合型（before_model で両方を検索して注入。ツール呼び出し削減、実装複雑）→ ③階層型（Memory → product_docs → faq_docs の優先順を Instruction に）。矛盾時の優先順位も Instruction に明記（ポリシーは RAG、嗜好は Memory、矛盾は RAG 採用し変更を伝える）。

## 意思決定表（アーキテクト向け）

| 論点 | 判断基準 | 推奨 |
|---|---|---|
| Memory Bank を使うか | 過去の対話を踏まえた応答が業務価値を生むか | Yes → 導入、No → Session のみ |
| RAG Engine を使うか | 静的な社内文書に基づく回答が必要か | Yes → 導入、No → 関数ツールで API 連携 |
| 併用 | 両方の情報源を扱うか | 多くの実務ケースで標準。優先順位を Instruction に |
| PII | Memory Bank に PII が入り得るか | 同意取得・削除フロー設計 |
| コスト | Vertex AI 料金を許容できるか | 月次見積もり。Compaction 閾値で制御 |

## 関連アンチパターン

Memory Amnesia（InMemory のまま本番・State 設計欠落・Memory Bank 未設定 → 本番は必ず Database / VertexAi）、Config Drift（DB URL・モデルをコードに直書き → 環境変数 / 設定ファイル）。
