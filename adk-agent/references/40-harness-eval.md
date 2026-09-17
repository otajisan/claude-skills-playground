# 40 Harness: 評価 — adk eval で品質を測る

> いつ読むか: eval モード全体、design の評価計画、scaffold の eval セット雛形。
> 出典: 第 5 章 5.1〜5.3、第 9 章原則 7、付録 A（要約・再構成）

## なぜ評価が難しいか / 三位一体

非決定性（temperature 0 でも完全再現しない）・マルチステップ（ツール軌跡と途中判断を評価する必要）・主観的品質（正確さ / 網羅性 / 簡潔さ / トーン）。
評価で弱点を発見 → ガードレールで防御 → カバーできないケースは HITL。この循環が Harness Engineering。

## 評価セット（JSON）

```json
{
  "eval_set_id": "expense_eval",
  "eval_cases": [
    {
      "eval_id": "submit_normal",
      "conversation": [
        {
          "user_content": {"role": "user", "parts": [{"text": "..."}]},
          "final_response": {"role": "model", "parts": [{"text": "期待応答（キーワード・ID・金額など安定トークンを含める）"}]},
          "intermediate_data": {"tool_uses": [{"name": "submit_expense", "args": {"amount": 3000}}]}
        }
      ]
    }
  ]
}
```

- `conversation` は Invocation 配列。**マルチターン**は要素を順に並べ、2 ターン目の発話が 1 ターン目の文脈（京都・2 泊）を引き継ぐかを検証する
- `conversation` と `conversation_scenario`（User Simulation 用）は排他。両方 / 両方なし はバリデーションエラー
- 安全性ケースは `tool_uses: []`（ツールを呼ばないことを期待）
- `final_response` は厳密一致ではなく類似度で評価。**日本語だけの短い定型文は ROUGE-1 のトークナイズで 0 になり得る** → エラーコード・ID・金額・日付などの英数字トークンを含めるか、LLM-as-judge 系メトリクスを使う

### 6 カテゴリ（網羅する）

正常系（ハッピーパス）／ツール選択／エラーハンドリング／マルチターン（コンテキスト保持）／エッジケース（あいまい・矛盾・空入力・超長文）／安全性（有害リクエスト・インジェクション拒否）。件数目安: コードを書く前に 5 件、本番前 30 件（正常 / 異常 / 境界 / セキュリティ / 回帰の 5 分類）。

## 実行

```bash
adk eval <agent_dir> eval/eval_set.json [eval/other.json ...] \
  --config_file_path eval/eval_config.json --print_detailed_results
# <agent_dir> は agent.py で root_agent を公開するディレクトリ（ヘルプの AGENT_MODULE_FILE_PATH 表記は古い）
```

失敗時は終了コード 1 → CI で自動失敗にできる。LLM-as-judge 系は実行ごとに微小変動・コストあり。評価再現性のため `generate_content_config=GenerateContentConfig(temperature=0)` を検討。

`eval_config.json`（フラット形式）: `{"criteria": {"tool_trajectory_avg_score": 0.8, "response_match_score": 0.6}}`。`threshold` / `match_type` を持つオブジェクト形式も可。

## メトリクス

| メトリクス | 評価対象 | スケール |
|---|---|---|
| `tool_trajectory_avg_score` | ツール選択・引数・呼び出し順序・不要呼び出しの有無 | 0〜1 |
| `response_match_score` | 参照テキストとの ROUGE-1 類似度 | 0〜1 |
| `response_evaluation_score` | 応答単体の論理一貫性（Vertex AI Evaluation テンプレート） | 1〜5（厳しめ 4.0 / 通常 3.5 / 最低 3.0） |
| `safety_v1` | 有害・危険応答 | 0〜1 |
| `multi_turn_task_success_v1` / `multi_turn_trajectory_quality_v1` / `multi_turn_tool_use_quality_v1` | マルチターン達成度（後者 2 つは reference-free） | 0〜1 |
| `rubric_based_final_response_quality_v1` / `rubric_based_tool_use_quality_v1` | 自前ルーブリック採点 | — |
| カスタム | `eval_config.json` の `custom_metrics.<name>.code_config.name = "module.func"` | 実装者定義 |

カスタムメトリクス関数のシグネチャ: `(eval_metric, actual_invocations, expected_invocations, conversation_scenario=None) -> EvaluationResult`。閾値は `eval_metric.criterion.threshold` から読む（`eval_metric.threshold` は None にされる）。

### ユースケース別選定

| ユースケース | 必須 | 推奨 |
|---|---|---|
| Q&A Bot | response_match | response_evaluation |
| タスク実行 | tool_trajectory | カスタム（ツール名一致） |
| コード生成 | カスタム（実行可能性） | response_evaluation |
| 対話型 | response_evaluation | カスタム（自然さ） |
| 安全性重視 | カスタム（安全性） | カスタム（PII 検出率） |

### 実践パターン

- **段階的品質ゲート**: dev 0.6 / 0.5 / 3.0 → staging 中間 → prod 0.9 / 0.8 / 4.0（tool_trajectory / response_match / response_evaluation）
- **カテゴリ別重み付け**: サポートは response_match 0.4、データ処理は tool_trajectory 0.5 で加重平均
- **回帰スナップショット**: ベースラインから 0.05 超の低下を回帰として報告

## 結果 → 改善アクション

| 症状 | 原因 | 対処 |
|---|---|---|
| tool_trajectory が低い | ツール選択・引数が期待と不一致 | Instruction にツールの Use Case を書く、tool description / docstring 改善 |
| response_match が低い | final_response が狭い / 表現差分に敏感 | final_response の書き方見直し、カスタムメトリクス・LLM-as-judge |
| ばらつきが大きい | LLM の非決定性 | 複数回実行して分布確認、temperature 0 |

改善サイクル（評価セット作成 → 実装 → adk eval → 結果分析 → Instruction / ガードレール / HITL 改善）を **最低 2 回**。発見した失敗事例は評価ケースに追加して資産化する。

## User Simulation（ペルソナ評価）

固定ケースでは初心者（あいまい・前提省略）/ 上級者（専門用語・効率）/ 敵対的（インジェクション）を網羅できない。`ConversationScenario`（`starting_prompt` / `conversation_plan` / `user_persona`）を `scenarios.json` に定義し、LLM がユーザー役を演じる。

```bash
adk eval_set create ./my_agent persona_set
adk eval_set add_eval_case ./my_agent persona_set --scenarios_file scenarios.json --session_input_file session_input.json
adk eval ./my_agent persona_set --config_file_path eval_config.json --print_detailed_results
# Vertex AI Eval SDK でシナリオ生成: adk eval_set generate_eval_cases ... --user_simulation_config_file cfg.json
```

ペルソナ設計: 実ログ・インタビューから抽出／多様性軸（技術レベル・スタイル・粘り強さ・意図・言語・感情）／ゴールとアンチゴール（「確認を省略させようとする管理者」）を明示。
分析: 特定ペルソナのスコア低下 → Instruction にガイダンス追加／ターン数が max に近い → 冗長・意図理解不足／敵対的ペルソナがゴール達成 → ガードレール強化。

## その他の CLI

- `adk test <folder> [--rebuild]`: `.test.json` を pytest で回す軽量回帰
- `adk conformance record tests/conformance {none|sse|bidi}` / `adk conformance test tests/conformance --streaming-mode sse`: 記録済みの LLM リクエスト / ツール呼び出し / SSE イベントとの整合を検証（A2A 準拠テストではない）。`--generate_report` / `--report_dir`
- `adk optimize <agent_dir> --sampler_config_file_path optimize/sampler_config.json`: GEPA で root_agent の Instruction を最適化（評価セットは LocalEvalSampler 設定経由）

## CI 統合

`.github/workflows/agent-eval.yml`（`templates/ci/`）: PR で `adk eval` を複数セット実行 → `scripts/check_eval_thresholds.py` で閾値未達なら `sys.exit(1)` → マージブロック。Cloud Build なら pytest → adk eval → adk deploy の順で品質ゲートにする。

## 関連アンチパターン

Eval Neglect（「手で試して動いた」で本番投入 → 5 分類 30 件 + CI）。設計レビュー Q-1〜Q-5 の根拠。
