# 20 Context Engineering — LLM に何を見せるか

> いつ読むか: design で Instruction / コールバック方針を決めるとき、scaffold / harden でコールバックを書くとき。
> 出典: 第 3 章（要約・再構成）

## なぜ全部入れてはいけないか

コンテキストウィンドウが 100 万トークンあっても、**コスト**（入力トークン比例）・**レイテンシ**（TTFT 増）・**精度**（Lost in the Middle: 中間に置かれた情報は参照確率が下がる）の 3 点で「全部入れ」はアンチパターン。

**コンテキスト予算**を事前に配分する（例: 運用予算 128K のカスタマーサポート）: System Instruction 10% / ユーザー情報 5% / 会話履歴 30% / ツール結果 25% / 動的コンテキスト 15% / 出力バッファ 15%。配分は動的に調整し、長い会話では履歴を圧縮する。

**コンテキスト汚染 3 パターン**と対策:

| 汚染 | 症状 | 対策 |
|---|---|---|
| 蓄積型 | 古いツール結果が残り新しい結果の解釈を歪める | Compaction（`30-memory-engineering.md`） |
| 矛盾型 | System Instruction と履歴 / ツール結果が矛盾 | 動的 Instruction で状態に応じた指示、優先順位ルールを明記 |
| ドメインリーク型 | 他サブエージェントの用語・指示が混入 | `output_key` で公開情報を限定、責務分離 |

設計要素と ADK 機能の対応: 情報の選別（State スコープ / Instruction / before_model_callback / ツール結果整形）、注入タイミング（静的・動的 Instruction）、順序制御・フィルタ（before_model_callback / after_tool_callback）、検証（after_model_callback）、スキルの構造化（Agent Skills）。

## コンテキスト型の選択（v2.2.0）

| 型 | State 読/書 | Artifact | 使う場所 |
|---|---|---|---|
| `InvocationContext` | 可/可 | 可 | Runner 内部、`BaseAgent._run_async_impl` |
| `ReadonlyContext` | 可/不可 | 不可 | 動的 Instruction 生成（冪等性を型で保証） |
| `Context`（`CallbackContext` / `ToolContext` は互換エイリアス） | 可/可 | 可 | コールバック、ツール関数、Workflow ノード |

選択フロー: State を変更する？ No → `ReadonlyContext`。Yes → Artifact 操作が必要？ Yes → ツール関数の `tool_context`。コールバック内？ → `callback_context`。カスタムエージェント → `InvocationContext`。**「とりあえず InvocationContext」はアンチパターン**。

マルチエージェントは同一 Session を共有する。State はプレフィックスで役割分離（`app:` 全ユーザー共通 / `user:` ユーザー単位 / なし Session / `temp:` 1 Invocation）。

## Instruction 設計

### 3 種類

| 種類 | 定義 | 用途 |
|---|---|---|
| 静的 | 固定文字列 | 役割・基本ルール（明確・再現性） |
| 動的 | `def build(ctx: ReadonlyContext) -> str` | State に応じた指示（会員ティア、言語、アクティブ注文）。副作用なし・肥大化させない・重い処理を入れない |
| グローバル | `App(plugins=[GlobalInstructionPlugin(global_instruction=...)])` | 全サブエージェント共通ポリシー（言語・トーン・根拠明示）。`Agent.global_instruction` は非推奨 |

### 4 要素 × 3 スコープ

4 要素 = 役割 / 目標 / 制約 / 出力形式。組織共通ポリシーはグローバル、役割は各エージェントの静的、状態依存は動的に振り分けて肥大化と重複を防ぐ。

### ベストプラクティス

1. 役割と対応範囲を最初に宣言し、範囲外はエスカレーション
2. 制約は否定形でなく肯定形（「不確かな情報を伝えない」→「確認できた事実のみ伝え、不確かなら確認中と回答」）
3. 出力形式を番号付きで明示（`output_key` と組み合わせる）
4. 停止条件を明示（回答完了 / エスカレーション判断 / ユーザーの終了発言）
5. 静的と動的を分離
6. ツールは **いつ使うか（Use Case）** を書く。書かないとツールが呼ばれない
7. トークン効率: 修飾語（「非常に優秀な」）は品質に寄与しない。手順は箇条書き

### テンプレートパターン

- **ROLE-TASK-FORMAT**: `## Role` / `## Task` / `## Format` の 3 セクション
- **CONTEXT-SPECIFIC**: 静的部分 + `## Current Context`（State から取得したユーザー名・ティア・アクティブ注文）
- **ESCALATION-AWARE**: エスカレーション条件（明示要求 / 3 回以上未解決 / 金額修正・特別対応）と時の動作（`escalate` ツール + 要約）、State のエスカレーション回数を埋め込む

## コールバック（4 種 + agent 前後）

共通規約: **None を返すと続行、値（`LlmResponse` / `dict`）を返すと差し替え・スキップ**。`before_model` で `LlmResponse` を返すと LLM は呼ばれない（キャッシュヒット時のスキップにも使える）。

| コールバック | シグネチャ | 典型用途 |
|---|---|---|
| `before_model_callback(callback_context, llm_request)` | → `LlmResponse \| None` | コンテキスト注入（`llm_request.contents.append(...)` / `append_instructions`）、レート制限、インジェクション検出、Kill Switch |
| `after_model_callback(callback_context, llm_response)` | → `LlmResponse \| None` | 禁止ワード・PII マスク、ハルシネーション疑い記録、エスカレーション判定 |
| `before_tool_callback(tool, args, tool_context)` | → `dict \| None` | RBAC、引数検証（パストラバーサル・SQL）、HITL 承認、実行回数制限、監査ログ |
| `after_tool_callback(tool, args, tool_context, tool_response)` | → `dict \| None` | 結果トリミング（上位 5 件）、間接インジェクション検出、PII マスク |

実行順序: before_model → LLM → (ツール呼び出しごとに before_tool → ツール → after_tool → 再度 before_model → LLM …) → after_model。

**合成パターン**: 関心事ごとに関数を分け `compose_*(*callbacks)` で順に適用、最初に非 None を返した時点で早期リターン。順序に意味がある（コストの低いチェック → レート制限 → インジェクション検出 → 注入）。

**コールバックに向く処理**: 横断的関心事（ログ・認証・レート制限）、ガードレール、コンテキスト補強、モニタリング。**向かない処理**: ビジネスロジック（Instruction とツールで）、複雑な状態管理（カスタムエージェント）、長時間の外部 API（ツールにする）。

**テスト**: 通常の Python 関数なので `MagicMock()` で `ctx.state = {}` を代用し、`LlmRequest` / `LlmResponse` を組み立ててユニットテストできる（`templates/tests/test_callbacks.py`）。

デバッグ: `State` は `dict()` 変換不可 → `callback_context.state.to_dict()`。`adk run` に `--log_level` は無い → `adk web . --log_level debug`（`-v`）か、コールバック内で `logging`。

## Agent Skills（agentskills.io 準拠、`google.adk.skills`）

**指示と参照資源のパッケージ**。関数ツールは「能力」、スキルは「手順書」という責務分離。Progressive Disclosure の 3 階層:

- L1 Metadata: `SKILL.md` の frontmatter（`name` kebab-case・ディレクトリ名と一致 / `description` / `allowed-tools`（experimental）/ `metadata`）。常時 LLM に提示され、どのスキルを呼ぶかの判断材料
- L2 Core Instruction: `SKILL.md` 本文。`load_skill` 時に渡す（対応範囲・手順・注意事項）
- L3 Optional Resources: `references/`（手順書・ポリシー）/ `assets/`（参照データ）/ `scripts/`（シェル。Python ツールは置かない）。`load_skill_resource` で個別読み込み

読み込み: `load_skill_from_dir(path)` → `SkillToolset(skills=[...])` を関数ツールと並列に `tools=` へ。SkillToolset は `list_skills` / `load_skill` / `load_skill_resource` を自動生成する。

再利用 3 パターン: 共通スキルライブラリ（common_skills / domain_skills）、条件付き読み込み（`user_role` でスキル集合を切替）、バージョニング（`metadata.version` + `order-management-v2/` ディレクトリ、user_id ハッシュで A/B）。

ベストプラクティス: 単一責任（ドメインごとに分離、everything スキル禁止）／ **SKILL.md 内のツール名と `tools=` の関数名を一致させる**（機械検出できないのでレビューで突き合わせる）／ 関数ツールの型・docstring を厳密に／ 破壊的変更はバージョン付きディレクトリで共存。

MCP との関係: MCP はツールを呼ぶ配管、Agent Skills は指示のパッケージ。同じ `tools=` に `SkillToolset` と `McpToolset` を並列登録できる。

## 関連アンチパターン

Prompt Spaghetti（「ただし」の連鎖 → 方針 / フロー / 詳細ルールを分離し、詳細は Agent Skills へ。200 トークン超で構造化、500 超で外部化）、Phantom Context（ツールがあるのに訓練データで答える → 「必ずツールで確認してから回答」「見つからなければその旨を回答」「事実情報は推測しない」を必須ルールに）。
