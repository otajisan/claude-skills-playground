# 41 Harness: ガードレール・HITL・Kill Switch

> いつ読むか: harden モード全体、design で承認ポイント・権限を決めるとき、review の S / O 項目。
> 出典: 第 5 章 5.4〜5.5、第 9 章原則 5・9、第 10 章 10.4（要約・再構成）

## 多層防御（5 層）

1 層突破されても次で止める。基本原則は **早期遮断**（不正入力は LLM に渡す前にブロック = コストと安全の両立）と **透明性**（ブロック理由をユーザーに示す）。

| 層 | 実装箇所 | 役割 |
|---|---|---|
| L1 入力フィルタ | `before_model_callback` | プロンプトインジェクション / 禁止トピック / レート制限 / Kill Switch / エスカレーション判定 |
| L2 Instruction | `instruction` | 役割・禁止事項・セキュリティルール（LLM が従う保証はないので L1/L3/L5 と併用） |
| L3 ツール実行前 | `before_tool_callback` | 引数検証（SQL / パストラバーサル）/ RBAC / 金額上限 / 実行回数制限 / HITL 承認 |
| L4 ツール結果検証 | `after_tool_callback` | 間接インジェクション検出（`[SYSTEM]` 等の制御マーカー）/ PII マスク |
| L5 出力フィルタ | `after_model_callback` | 機密情報マスク（メール・電話・API キー）/ 禁止表現 / ハルシネーション疑い記録 |

ガードレール内の例外は **安全側に倒す**（try/except でエラーログ + 固定応答でブロック）。状態を持つ機構（Kill Switch・Escalation）はスレッドセーフに。

## ガードレールの構成パターン

- **レイヤード**: リストを順に適用、最初に非 None で早期リターン。コストの低いチェックから（レート制限 → インジェクション → トピック）
- **コンテキスト依存**: `user_role` で厳格さを変える（guest は禁止トピック多・入力長短、admin は制限なし）
- **ソフトブロック（段階的エスカレーション）**: high はブロック、medium は「続行を確認します」と入力させて通過（`_user_confirmed` フラグ）

厳格度トレードオフ: 高（偽陽性多・偽陰性少）= 金融・医療・法律、中 = 一般ビジネス、低 = 社内ツール・開発環境。

入力検出の実装: 正規表現（「指示を無視」「ignore previous instructions」「jailbreak」「DAN」等）は第一防御線。難読化（Unicode 置換 → NFKC 正規化、Base64 → デコード後検査、多段プロンプト → セッション全体で検出、ロールプレイ誘導、言語切替）には LLM ベース分類器（軽量モデル、temperature 0、`safe` / `unsafe` の 1 語）を **疑わしいリクエストだけ** に適用。

PII マスク: メール `[EMAIL]`、電話 `[PHONE]`、マイナンバー、カード番号、Google API キー（`AIza...`）。高精度が必要なら Cloud DLP（`InspectConfig` / `DeidentifyConfig`）を発展的に統合。

ガードレールのテスト: 正常通過（None）と検出（非 None）の両方を pytest で。`MagicMock()` で context を代用。

## HITL（Human-in-the-Loop）

ルールで全リスクは定義できない（高額送金・一括更新・法的判断・前例なし）。**リスク × 可逆性** で 4 象限:

| | 可逆 | 不可逆 |
|---|---|---|
| 高リスク | HITL 承認要（一括更新・権限変更） | 人間のみ承認（本番 DB 全件削除・高額送金） |
| 低リスク | 完全自動（FAQ・下書き） | 通知つき自動（社内通知・ログ） |

### 承認ポイント設置基準 6 つ

影響範囲（多数レコード）／可逆性（削除・送金）／金額（閾値超）／権限（管理者操作）／法的リスク／前例なし。いずれか 1 つ超えたら承認フロー。多すぎると自動化の価値が消え、少なすぎるとリスクが残る。

### 実装パターン

- **同期（before_tool_callback）**: `APPROVAL_RULES = {tool_name: {condition(args), message}}`。条件一致 & 未承認なら `_pending_approval` を State に保存して `{"status": "approval_required", "message": "承認する場合は「承認: <id>」と入力"}` を返してツールをスキップ。`before_model_callback` でユーザーの「承認: id」を検出して `_approval_<tool>` フラグを立て、次の呼び出しで通す。**承認対象ツールは `tools=` に登録しないと before_tool_callback が発火しない**
- **Workflow 組み込み**: `request_input` ツール（標準化）+ `@node(rerun_on_resume=True)` で中断・再開。A2A では `TASK_STATE_INPUT_REQUIRED` になる
- **`LongRunningFunctionTool`**: 承認 ID を返して Runner を一時停止、function_response で再開。Slack 通知等と組み合わせる
- **非同期承認**: Firestore 等に `approval_requests`（`status` / `approvers` / `decisions` / `expires_at` 24h）を作り承認者に通知。バッチ処理向け。日次 10 件未満なら Slack 通知で十分、増えたらダッシュボード

### エスカレーション設計

`ESCALATION_RULES`（連続エラー 3 回 → L2 サポート、信頼度低、ユーザー不満、センシティブトピック）を `after_model_callback` で判定し、引き継ぎメッセージ（やり取り要約付き）を返す。

### HITL アンチパターン

過剰承認（全操作に承認 → リスクベースで厳選）／承認疲れ（優先度付け・バッチ化）／タイムアウト未設定（フォールバック設定）／単一承認者（複数 + エスカレーションチェーン）／コンテキスト欠如（判断材料を含める）。

## 段階的自律性（原則 5）

| 自律レベル | low | medium | high | critical |
|---|---|---|---|---|
| FULL_HITL (0) | 承認 | 承認 | 承認 | 承認 |
| SUPERVISED (1) | 自動 | 承認 | 承認 | 承認 |
| SEMI_AUTONOMOUS (2) | 自動 | 自動 | 承認 | 承認 |
| AUTONOMOUS (3) | 自動 | 自動 | 自動 | 承認 |

`TOOL_RISK_LEVELS = {tool_name: "low|medium|high|critical"}` と State の `autonomy_level` を `before_tool_callback` で照合。新規は 0 から、承認率 95% 超で昇格。

## Kill Switch（原則 9 / 第 10 章）

4 要件: 即時性・確実性（LLM 判断に依存しないコードレベル停止）・粒度（global / agent / tool）・復元性。
実装: スレッドセーフな `KillSwitch`（`_global_kill` / `_agent_kills` / `_tool_kills`、`threading.Lock`）。`before_model_callback` で agent 停止中なら固定応答（「メンテナンス中」）、`before_tool_callback` で tool 停止中ならエラー dict。状態は本番ではフィーチャーフラグストア等の外部から取得。**合成の最優先**に置く。

### 段階的エスカレーション（10.4.2）

| レベル | トリガー | アクション |
|---|---|---|
| 1 Warning | 軽微な異常（短時間の大量リクエスト） | ログ記録のみ（時間経過で解除） |
| 2 Restricted | 短時間に連続異常（警告 3 回 / 10 分） | 高リスクツール拒否・頻度制限 |
| 3 Stopped | 異常継続・重大 | エージェント停止（固定応答）。管理者操作で解除 |
| 4 HITL | 判断不能な未知の異常 | オペレーターに対応要求 |

`EscalationManager` がユーザーごとの `UserIncidentTracker` を持ち、`escalation_callback`（before_model）で STOPPED / HUMAN_ESCALATION なら固定応答。

### 実行回数制限

`ExecutionLimiter(max_calls_per_session=50, max_calls_per_tool=10)` を `before_tool_callback` に。State の `_total_tool_calls` / `_tool_calls_<name>` でカウント。`LoopAgent.max_iterations` / `RunConfig.max_llm_calls` / Instruction の終了条件と多重防御（Infinite Loop 対策）。ループ検知: 直近 3 回が同一ツール・同一引数なら停止。

## フェイルセーフ 3 レイヤー（原則 9）

1. ツール: リトライ（一時的エラー）→ フォールバック（セカンダリ → キャッシュ）→ 全滅ならエラー dict
2. エージェント: 1 ターンのツール呼び出し上限、ループ検知
3. システム: Kill Switch

## 監査ログ

全コールバックで記録。項目: 識別（session_id / user_id / agent_name / trace_id）、入力（マスク済み）、LLM 呼び出し（モデル・トークン・レイテンシ）、ツール（名前・マスク済み引数・結果・所要）、エスカレーション（レベル・理由）、エラー。構造化 JSON で Cloud Logging へ（`80-security.md`）。
