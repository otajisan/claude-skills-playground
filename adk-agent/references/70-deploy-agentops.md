# 70 デプロイと AgentOps

> いつ読むか: deploy モード全体、design でデプロイ先・コスト観点を書くとき、review の O / C 項目。
> 出典: 第 8 章、付録 A-9（要約・再構成）

## デプロイ先の選定

| 観点 | Agent Engine | Cloud Run | GKE |
|---|---|---|---|
| デプロイ | `adk deploy agent_engine` | Dockerfile + `gcloud run deploy`（`adk deploy cloud_run` も可） | Dockerfile + マニフェスト（`adk deploy gke`） |
| Session 永続化 | `VertexAiSessionService` 自動統合 | 自前（`DatabaseSessionService` + Cloud SQL 等） | 自前 |
| スケーリング | 自動（ゼロスケール非対応、最小 1） | リクエスト駆動、ゼロスケール可 | HPA / VPA |
| カスタムドメイン | 非対応（API 経由のみ） | 対応 | 対応 |
| GPU | 非対応 | 対応 | 対応 |
| Interactions API / Memory Bank / Trace | 組み込み・ネイティブ・`--otel_to_cloud` | 自前 / SDK / 手動計測 | 同左 |
| 運用負荷 / 柔軟性 | 最低 / 低 | 低〜中 / 中 | 中〜高 / 最高 |
| 課金 | Runtime（vCPU・GiB 時間）+ Sessions + Memory Bank + Code Execution 従量 | リクエスト + vCPU / メモリ | ノード + リソース（固定費） |

選定フロー: ADK エージェント？ No → Cloud Run / GKE。GPU 必要？ → GKE。カスタムドメイン必須 / ゼロスケール必須？ → Cloud Run。複雑なネットワーク → GKE。運用チーム小（1〜3 名）→ Agent Engine、中 → Agent Engine or Cloud Run、大 → Cloud Run or GKE。

推奨: PoC / MVP は Agent Engine 一択（従量課金は検証予算に含める）。小〜中規模本番は Agent Engine 第一選択。大規模 / マルチテナントは GKE。ハイブリッド（コアは Agent Engine、カスタムツールサーバーは Cloud Run）。TCO（運用人件費込み）で判断。

Cloud Run / GKE は Agent Engine 組み込みの Session 永続化・ヘルスチェック・認証・モニタリングを自前実装。HTTP API で `session_id` を受けるなら `get_session` で存在確認 → 無ければ `create_session(..., session_id=)`。コンテナには `asyncpg` / `aiosqlite` + `greenlet` を含める。

マイグレーション: Agent Engine → Cloud Run（HTTP サーバー化・Session 移行・OTel 再構築）、Cloud Run → GKE（イメージ流用、マニフェスト・ConfigMap / Secret）。Blue-Green / カナリア、メンテナンスウィンドウ、並行監視、ロールバック用に移行元保持。

## ローカルと Agent Engine の差異

| 項目 | ローカル | Agent Engine |
|---|---|---|
| Session | InMemory | VertexAi |
| 環境変数 | `.env` | `.agent_engine_config.json` / Secret Manager |
| ファイルシステム | 永続 | エフェメラル（リクエスト間で共有されない → GCS / DB へ） |
| 認証 | ADC | サービスアカウント |
| ログ / トレース | 標準出力 / なし | Cloud Logging / `--otel_to_cloud` |
| タイムアウト | なし | あり（長時間は `LongRunningFunctionTool`） |

リクエスト処理フロー: IAM 認証 → Session 復元（履歴が長いほど遅い → Compaction）→ Runner.run → LLM 推論（ツール呼び出しごとに推論が増える）→ ツール実行 → sub_agent 委譲（ネストごとにオーバーヘッド。3 層以内）→ Session 保存 → 応答。

## `adk deploy agent_engine`

前提 API: `aiplatform` `storage` `logging` `monitoring` `telemetry` `cloudtrace` `cloudresourcemanager`（+ `secretmanager`）。依存: `google-adk[gcp,otel-gcp]==2.2.0`、`google-cloud-aiplatform[agent-engines]==1.153.1`（広い範囲指定だと OTel 上限を超える版が選ばれることがある）、`opentelemetry-exporter-otlp-proto-http==1.41.1`。`google-cloud-aiplatform` の `adk` extra は `google-adk<2` を要求するので併用しない。

```bash
adk deploy agent_engine ./my_agent --project P --region us-central1 \
  --display_name "support-agent-v2.1" --description "..." \
  --agent_engine_config_file .agent_engine_config.json --otel_to_cloud
# 他: --agent_engine_id（既存更新）--trigger_sources pubsub,eventarc --adk_version 2.2.0
#     --session_service_uri / --artifact_service_uri / --memory_service_uri
# --staging_bucket --env_file --requirements_file --trace_to_cloud は非推奨（otel_to_cloud / config file / Secret Manager へ）
```

プロジェクト構造は `adk create` 準拠 + `requirements.txt`（`.env` はデプロイに含まれない）。

### 3 種類の ID と IAM

| ID | 役割 | ロール |
|---|---|---|
| デプロイ運用者（ユーザー / SA） | 作成・更新・削除 | `roles/aiplatform.user` + `roles/storage.admin`（付録 A: `storage.objectAdmin` / `iam.serviceAccountUser`。初回のみ `serviceusage.serviceUsageAdmin`） |
| 呼び出しクライアント | Interactions API | `roles/aiplatform.user` |
| サービスエージェント（`service-<PROJECT_NUMBER>@gcp-sa-aiplatform-re.iam.gserviceaccount.com`） | エージェント自身が外部リソースにアクセス | `reasoningEngineServiceAgent` 自動付与 + 必要なもの（例 `bigquery.dataViewer`） |

`roles/aiplatform.admin` は常時付与せずデプロイ時のみ。Cloud Audit Logs でデプロイ追跡。Cloud Run は `run.admin` / `artifactregistry.writer` / `cloudbuild.builds.editor` / `iam.serviceAccountUser`。

### 設定とシークレット

非機密は `.agent_engine_config.json`（`--env_file` 単体より集約管理を優先）、`os.environ.get("LOG_LEVEL", "INFO")`。機密は Secret Manager（`gcloud secrets create`、SA に `secretmanager.secretAccessor`、`get_secret(secret_id, project_id)` で `versions/latest`）。

### バージョンとロールバック

versioned fields 更新で不変 revision。トラフィック分配（割合指定 → カナリア / ロールバック）は Preview。運用: デプロイごとに Git タグ、`display_name` にバージョン、旧 revision を一定期間保持、ロールバックはトラフィック切替。

### CI/CD（Cloud Build / GitHub Actions）

pytest → `adk eval`（品質ゲート）→ `adk deploy agent_engine --display_name support-agent-${SHORT_SHA}` → ステージング検証 → promote。

### Python SDK

`vertexai.Client(project, location).agent_engines.create(agent=agent_engines.AdkApp(agent=root_agent), config={display_name, requirements, env_vars: {GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY: "true", OTEL_SEMCONV_STABILITY_OPT_IN: "gen_ai_latest_experimental", OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT: "EVENT_ONLY"}, staging_bucket})`。ヘルスチェック・スモーク・Slack 通知を組み込める。

### トラブルシューティング

`ModuleNotFoundError`（requirements 漏れ）/ `ImportError`（`__init__.py` の `root_agent` 公開）/ `Permission denied`（`aiplatform.user` `iam.serviceAccountUser`）/ `Quota exceeded` / `Timeout during deployment`（`.gcloudignore`）/ リージョン未提供（`us-central1` 等へ）。

### デプロイ前チェックリスト（表 8.4）

1. `adk web` / `adk run` でローカル動作確認済み
2. `__init__.py` で `root_agent` をエクスポート
3. `requirements.txt` に全依存
4. `.env` の内容が `.agent_engine_config.json` / Secret Manager で扱える
5. SA に必要権限
6. 対象リージョンで Agent Engine 利用可
7. `adk eval` で品質基準クリア
8. Git コミット済み（バージョン追跡）

## Interactions API

`agent_engine = vertexai.agent_engines.get(resource_name)` → `await agent_engine.async_create_session(user_id)` / `async_list_sessions` / `async_delete_session` → `async for event in agent_engine.async_stream_query(user_id, session_id, message)`（`content` チャンク / `tool_call` / `is_final`）。同期 `stream_query` は非推奨。パターン: チャットボット / FastAPI + SSE（`StreamingResponse`）/ バッチ（`asyncio.Semaphore(5)`）。

エラー: 400 InvalidArgument（リトライ不要）/ 404 NotFound（セッション再作成）/ 429 ResourceExhausted（指数バックオフ）/ 500（3 回まで）/ 503（バックオフ）。

## スケーリングとコスト

- オートスケール: 数秒〜数十秒で追加。急スパイクにはウォームアップ。最小 1 インスタンス（コールドスタート回避）
- **コスト最適化レバー**: ①責務分離（短い Instruction のルーター + 専門エージェント）②Compaction（トークン量を減らす）③コンテキストキャッシュ（Gemini Context Caching `types.CachedContent(ttl="3600s")`。**単価を下げる**。10K トークン超のコンテキストで効果大。ADK 経由は Gemini 系のみ、Claude on Vertex では使えない。global エンドポイントはキャッシュ保管リージョンが特定できない → PII / データレジデンシー要件を確認）④バッチ（`BatchPredictionJob`、大規模評価・定期レポート・大量分類）
- タスク別方針: ルーティング → 短い Instruction / FAQ → キャッシュ / 抽出・要約 → 出力スキーマ / 複雑推論 → 評価セット / コード生成 → テスト実行 / 創作 → 人手レビュー

> 現場の教訓（BLUEISH コラム）: Office 系 MCP の巨大な検索結果 + 長い System Instruction を毎回フル送信し、開発環境だけで月 300 万円超。Compaction のチューニングでは下がらず、プロンプトキャッシュで約半減。**ツール統合を始めた瞬間にコスト監視ダッシュボードを先に立てる**。トークン量を減らすレバー（Compaction）と単価を下げるレバー（Cache）は別物で両方効かせる。

コスト監視メトリクス: 入力トークン / リクエスト（前日比 150% で警告）、出力トークン / リクエスト（200%）、日次総コスト（予算 80%）、モデル別内訳、Compaction 発火回数。週次で前週比 20% 増なら調査。

## AgentOps（Build → Eval → Deploy → Monitor → Improve）

- **Monitor**: Cloud Trace（`--otel_to_cloud`。1 リクエスト = 1 トレース、`agent.run` / `llm.generate_content`（model, tokens_in/out）/ `tool.call` の Span 階層。`agent.version` 等のカスタム属性で比較。プロンプト内容の記録は `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY`、同意・保持方針を先に整備）、Cloud Logging（構造化 JSON: severity / message / component / agent_name / session_id / user_id / tool_name。`logger.warning(..., extra={...})`。ログベースメトリクス `gcloud logging metrics create`）
- **SLI / SLO 基本セット**: 可用性 99.5% / レイテンシ P99 30 秒以内 / エラー率 5% 以下 / ツール呼び出し成功率 95% 以上 / 日次トークン消費 予算の 120% 以下。エラーバジェットを使い切ったら新機能を止めて信頼性へ
- **アラート 3 層**: インフラ（CPU 90% / メモリ 80% / P99 > 30s、Critical）/ エージェント（エラー率 5% / ツール失敗率 10% / 無限ループ、High）/ ビジネス（エスカレーション率 20% / 満足度低下、Medium。集計ウィンドウ 1 時間以上、通知先はビジネス側）。持続時間閾値でノイズ除外
- **エージェント特有の障害**: 無限ループ（呼び出し回数監視 → 上限・タイムアウト）/ ハルシネーション（品質スコア → ガードレール・RAG）/ コンテキスト汚染（トークン監視 → Compaction・分割）/ ツール誤用（ログ分析 → Instruction・説明強化）/ カスケード障害（階層的エラー率 → サーキットブレーカー・フォールバック）/ コスト暴走（予算アラート・自動停止）
- **インシデント対応**: トリアージ 5 分（P1 全停止 15 分以内 / P2 1 時間 / P3 営業日 / P4 次スプリント）→ 調査 15 分（Trace / Logging / メトリクス）→ 緩和 30 分（ロールバック・トラフィック制限・機能無効化）→ 復旧（根本修正・評価・再デプロイ）→ ポストモーテム
- **ダッシュボード 4 枚**: サービスヘルス（RPS / エラー率 / P50-P99 / アクティブセッション）/ エージェント品質（完了率 / エスカレーション率 / 満足度 / ハルシネーション検知）/ コスト / セキュリティ（認証失敗 / ガードレール発火 / 不審リクエスト）
- **Improve**: フィードバック源（監視データ / ユーザー評価 / adk eval トレンド / ポストモーテム）→ 分析 → 優先度（影響度 × 修正コスト × リスク）→ 実施（Instruction / ツール / ガードレール / モデル）→ 検証（adk eval 回帰・A/B・監視）。1〜2 週間スプリント。`adk optimize`（GEPA）は Instruction 最適化、ツール・メモリ・ガードレールは人間の設計判断
