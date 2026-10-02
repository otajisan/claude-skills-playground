# adk-cli — ADK CLI リファレンス要約（v2.2.0）

> いつ読むか: 動作確認コマンドを提示するとき、`--*_service_uri` や環境変数の罠を確認するとき。
> 出典: 付録 A（要約・再構成）。最新は `adk --help` / `adk <sub> --help` と公式ドキュメント

## サブコマンド一覧

| サブコマンド | 概要 |
|---|---|
| `create` | 雛形生成（`__init__.py` / `agent.py` / `.env`）。`--model` を明示（省略時は対話選択）。APP_NAME はハイフン不可 |
| `run` | CLI で対話実行 / 単発クエリ |
| `web` | ブラウザ UI（チャット・Session Info・Event Log・State インスペクタ） |
| `api_server` | Web UI なしの API サーバー（主要オプションは web と共通） |
| `eval` / `eval_set` | 評価セットの実行 / 生成・管理 |
| `test` | `.test.json` による pytest 回帰（`--rebuild` で再生成） |
| `conformance` | 記録済み ADK 実行との挙動整合性テスト（`record` / `test`） |
| `optimize` | GEPA による Instruction 最適化（`--sampler_config_file_path` 必須） |
| `deploy` | `agent_engine` / `cloud_run` / `gke` |
| `migrate` | 旧形式データ移行（`migrate session`。事前バックアップ） |

## adk run

```
adk run [OPTIONS] AGENT [QUERY]
  --save_session --session_id ID          # JSON に保存
  --resume sessions/ID.json               # 保存済みから再開
  --replay input.json                     # 非対話で再生（CI 向き）
  --state '{"user:tier":"premium"}'       # 初期 State
  --timeout 30s                           # 1 ターンのタイムアウト
  --jsonl                                 # 構造化 JSONL 出力（Workflow root / 動的 Instruction の確認はこれが主経路）
  --in_memory                             # 永続化せず
  --session_service_uri / --artifact_service_uri / --memory_service_uri
  --use_local_storage / --no_use_local_storage   # URI 未指定時にローカル .adk ストレージを使うか
  --default_llm_model MODEL               # model 未指定 Agent の既定
  --enable_features / --disable_features  # 実験機能
```

`--log_level` は **無い**（web にはある）。トラブル: `No root_agent found` → 変数名 / `__init__.py`、`GOOGLE_API_KEY not set`、`Permission denied` → `gcloud auth application-default login`、`Model not found`。

## adk web

```
adk web [OPTIONS] [AGENTS_DIR]   # 親ディレクトリで複数切替、エージェントディレクトリで単一モード
  --port 8000 --host 127.0.0.1（0.0.0.0 は外部公開に注意）
  --log_level debug | -v
  --allow_origins ORIGIN（繰り返し指定。カンマ区切り不可。regex: 可）
  --a2a                          # A2A サーバーモード
  --reload / --no-reload  --reload_agents
  --trace_to_cloud / --otel_to_cloud
  --eval_storage_uri gs://...
  --url_prefix  --trigger_sources  --extra_plugins  --logo-text / --logo-image-url
```

開発用 API: `GET /list-apps`、`GET /apps/{app_name}/app-info`（Root が LlmAgent 以外 / 動的 Instruction だとメタ情報表示が失敗することがある）。run と web はローカル開発専用。

| 観点 | adk run | adk web |
|---|---|---|
| 複数エージェント | 1 つずつ | 同時読み込み・切替 |
| イベント可視化 / State | ログ | イベントビューア / インスペクタ |
| CI | `--replay` で自動化 | 不向き |

## adk eval / eval_set

```
adk eval [OPTIONS] AGENT_DIR [EVAL_SET_FILE_PATH_OR_ID]...
  --config_file_path eval_config.json  --print_detailed_results  --eval_storage_uri  --log_level
adk eval_set create AGENT_DIR SET_ID
adk eval_set add_eval_case AGENT_DIR SET_ID --scenarios_file scenarios.json --session_input_file session_input.json
adk eval_set generate_eval_cases AGENT_DIR SET_ID --user_simulation_config_file cfg.json
```

AGENT_DIR は `agent.py` で `root_agent` を公開するディレクトリ（ヘルプの `AGENT_MODULE_FILE_PATH` 表記は古い）。全ケース全メトリクスが閾値以上で PASS、失敗は終了コード 1。`conversation` と `conversation_scenario` は排他。

## adk conformance

```
adk conformance record [PATHS...] {none|sse|bidi}       # input.yaml から記録
adk conformance test [PATHS...] --streaming-mode sse [--mode replay|live] [--generate_report --report_dir DIR]
```

PATHS 省略時は `tests/`。`spec.yaml` を含むディレクトリを指定。オプションは基本アンダースコア区切りだが `--streaming-mode` `--reload` `--logo-text` はハイフン。

## adk deploy

```
adk deploy agent_engine AGENT --project P --region R [--display_name --description --agent_engine_id --otel_to_cloud
    --agent_engine_config_file --trigger_sources pubsub,eventarc --adk_version 2.2.0 --temp_folder --*_service_uri]
adk deploy cloud_run AGENT --project P --region R [--service_name --app_name --port 8000 --with_ui --a2a --allow_origins
    --otel_to_cloud --adk_version --trigger_sources --*_service_uri --log_level]
adk deploy gke AGENT --project P --region R --cluster_name C [--service_type ClusterIP|LoadBalancer ...]
```

非推奨: `--staging_bucket` `--env_file` `--requirements_file` `--adk_app` `--absolutize_imports` `--trace_to_cloud`（→ `--otel_to_cloud` / `.agent_engine_config.json` / Secret Manager）。IAM: Agent Engine は `aiplatform.user` `storage.objectAdmin` `iam.serviceAccountUser`、Cloud Run は `run.admin` `artifactregistry.writer` `cloudbuild.builds.editor` `iam.serviceAccountUser`。`--with_ui` は検証用（本番は UI なし・認証済み API のみ）。

## サービス URI（run / web / api_server / deploy 共通）

| オプション | 形式 |
|---|---|
| `--session_service_uri` | `agentengine://ID`（またはフルリソース名）/ `sqlite:///sessions.db`（スラッシュ 3 つ。CLI ではドライバ不要）/ SQLAlchemy 対応 DB URL / `memory://` |
| `--artifact_service_uri` | `gs://BUCKET` / `file://PATH` / `memory://` |
| `--memory_service_uri` | `agentengine://projects/P/locations/R/reasoningEngines/ID` / `agentengine://ID`（PROJECT / LOCATION 環境変数から補完）/ `rag://RAG_CORPUS_ID` / `memory://` |

URI 未指定時: Session / Artifact は `--use_local_storage` に従いローカル `.adk` かインメモリ、Memory はインメモリ。URI を明示したら `--use_local_storage` は併用不可。Memory Bank / RAG Corpus は Vertex AI 側で事前作成・有料。取り込み / 検索はエージェント側の `add_session_to_memory()` / `PreloadMemoryTool` 等が必要。

## 環境変数

| 変数 | 説明 |
|---|---|
| `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` | プロジェクト / リージョン |
| `GOOGLE_APPLICATION_CREDENTIALS` | SA キーパス（ADC 設定済みなら不要） |
| `GOOGLE_API_KEY` | Google AI Studio API キー |
| `GOOGLE_GENAI_USE_VERTEXAI` | TRUE で Vertex AI 経路 |
| `ADK_DISABLE_LOAD_DOTENV=1` | エージェント `.env` の自動読み込みを無効化 |
| `ADK_FORCE_LOCAL_STORAGE` / `ADK_DISABLE_LOCAL_STORAGE` | ローカル `.adk` ストレージの強制 / 無効化 |
| `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS` | トレース span にメッセージ内容を含めるか |
| `ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS=1` | experimental 警告の抑制（A2A 等） |

優先順位: CLI オプション > シェルの環境変数 > `.env`（明示済みは上書きしない）> 組み込み既定。

**罠**: `GOOGLE_GENAI_USE_VERTEXAI=TRUE` + プレースホルダの `GOOGLE_CLOUD_PROJECT` が `.env` に残っていると、API キーを渡しても Vertex に接続して `PERMISSION_DENIED`。→ `FALSE` にするか `ADK_DISABLE_LOAD_DOTENV=1 GOOGLE_API_KEY=... adk run ...`。`.env` は平文なので `.gitignore` に。

## 逆引き

| やりたいこと | コマンド |
|---|---|
| 雛形作成 | `adk create my_agent --model gemini-3.5-flash` |
| 対話実行 / 単発 | `adk run ./my_agent` / `adk run ./my_agent "質問" --jsonl` |
| Session を SQLite に永続化 | `adk run ./my_agent --session_service_uri "sqlite:///sessions.db"` |
| Memory 接続 | `adk run ./my_agent --memory_service_uri "$URI"` |
| デバッグログ | `adk web . --log_level debug` |
| 評価 | `adk eval ./my_agent eval_set.json --config_file_path config.json --print_detailed_results` |
| 回帰 | `adk test ./my_agent` / `adk conformance test tests/conformance --streaming-mode sse` |
| Instruction 最適化 | `adk optimize ./my_agent --sampler_config_file_path optimize/sampler_config.json` |
| デプロイ | `adk deploy agent_engine ./my_agent --project P --region R --otel_to_cloud` |
