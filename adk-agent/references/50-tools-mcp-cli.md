# 50 ツール設計・MCP・CLI 統合

> いつ読むか: design でツール種別と接続方式を選ぶとき、scaffold で `tools.py` / McpToolset を書くとき、review の A-2 / S-1。
> 出典: 第 2 章 2.6〜2.7、第 6 章（要約・再構成）

## ツール種別の選定フロー

他エージェントの能力を使いたい → `AgentTool`。MCP サーバーとして提供済み → `McpToolset`。Google 検索 / コード実行 → 組み込み（`google_search` / `BuiltInCodeExecutor`、**Gemini 限定**）。シェルコマンド → `ExecuteBashTool`（本番はサンドボックス・コマンド制限）。実行が数分以上 / 人間の承認待ち → `LongRunningFunctionTool`。それ以外 → `FunctionTool`（Python 関数をそのまま `tools=` に渡してもよい）。

## FunctionTool 設計 7 原則

1. **docstring は LLM への説明書**: 1 行目がツール全体、`Args:` に各パラメータの説明と具体例（`area: 検索エリア（例: 京都駅周辺、嵐山）`）。`def search(q: str)` + 「検索する」では使えない
2. **エラーは dict で返す**: `{"status": "error", "error": "注文 ID '...' が見つかりません"}`。例外を raise すると実行が中断され得る。一時的エラーはツール内でリトライ、想定外の例外だけ伝搬
3. **冪等性**: 同じ呼び出しを繰り返しても安全（キャンセル済みなら `{"status": "success", "message": "すでにキャンセル済み"}`）。書き込みは冪等キー + upsert
4. **1 ツール 1 責務**: `handle_flight(action, **kwargs)` ではなく `search_flights` / `book_flight`
5. **ツール数は 1 エージェント 10 個以下**（5 個超で分割検討）。adk eval で測りながら適正数を決める
6. **戻り値は一貫した構造**: 全ツールが `status` を持つ dict → `after_tool_callback` で一括処理できる
7. **副作用ツールは確認メッセージ**: `message`（何をしたか）と `warning`（注意事項）を含める

型ヒントは必須（スキーマ自動生成に使う）。`Optional[int] = None` は required から外れ、省略時の挙動を docstring に書く。複雑な入力は Pydantic モデル（`Field(description=)` が反映）。値が限定される引数は `str` 継承 Enum。I/O バウンドは `async def`。`tool_context: ToolContext` 引数はスキーマに出ず ADK が注入（State 読み書き・`await tool_context.save_artifact(filename, types.Part)` ・認証要求）。

## ツール認証（第 2 章 2.7）

| 方式 | 用途 | 実装 |
|---|---|---|
| API Key | シンプルな REST | `os.environ["WEATHER_API_KEY"]`（直書き禁止。未設定はエラー dict） |
| OAuth 2.0 | ユーザー同意が必要（Google Calendar 等） | `OpenIdConnectWithConfig` + `AuthCredential(OAuth2Auth)` → `AuthConfig`。ツール内で `tool_context.get_auth_response(cfg)` が無ければ `tool_context.request_credential(cfg)` を呼び `{"status": "auth_required"}` を返す。認証後に再実行 |
| Service Account | Google Cloud サービス | ADC（`gcloud auth application-default login` / `GOOGLE_APPLICATION_CREDENTIALS`）。Cloud 環境では自動注入 |
| `AuthProviderRegistry` | 複数方式の一元管理 | experimental（`google.adk.auth.auth_provider_registry`） |

原則: 最小スコープ、Secret Manager / 環境変数、リフレッシュ自動化、401/403 は明確なメッセージ、認証を伴う呼び出しは監査ログ。

## MCP

Anthropic 提唱（2025 年 12 月に Linux Foundation AAIF 移管）。N×M 統合を N+M に。クライアント-サーバー、JSON-RPC 2.0。プリミティブ 3 つ: **Tools**（副作用あり・LLM が判断 → `McpToolset`）/ **Resources**（読み取り専用データ → コンテキストへ注入）/ **Prompts**（テンプレート → Instruction に活用）。ライフサイクル（initialize → tools/list → tools/call → shutdown）は `McpToolset` が管理。サンプリングコールバックも設定可。

### 接続パラメータ（v2.2.0、クラス名は `McpToolset`。`MCPToolset` は非推奨互換）

| クラス | トランスポート | 用途 |
|---|---|---|
| `StdioConnectionParams(server_params=StdioServerParameters(command, args, env, cwd), timeout=5.0)` | stdio | ローカルサブプロセス（`npx -y @modelcontextprotocol/server-filesystem <dir>`、`uvx ...`） |
| `StreamableHTTPConnectionParams(url, headers, timeout, sse_read_timeout, terminate_on_close)` | Streamable HTTP | リモート（推奨）。認証トークンは環境変数から `headers` に |
| `SseConnectionParams` | HTTP+SSE | 後方互換のみ。新規利用は非推奨 |

```python
McpToolset(connection_params=..., tool_filter=["query"] | callable(tool, readonly_context=None) -> bool, tool_name_prefix="bq")
```

- `tool_filter` で読み取り専用エージェントに書き込み系を出さない。callable なら名前・スキーマで判定（`write|delete|update|insert|drop|create` を含むものを除外）
- 複数サーバーは `tool_name_prefix` で名前衝突を防ぎ、Instruction にツールと用途を明記し、接続数は最小限
- ライフサイクル: `tools=[]` に直接渡して Runner に任せる（`runner.close()` / `async with Runner`）。単独利用なら `await toolset.close()`
- エラー処理: 全ツール呼び出しのログ、タイムアウト、一時エラーのリトライ（副作用ツールは冪等性確認）、サーバー利用不可時のフォールバック。パス引数は `before_tool_callback` で `..` / 絶対パスを拒否
- セキュリティ: stdio はプロセス権限、HTTP は OAuth 2.1 / API キー。入力検証（SQL / パストラバーサル）、最小権限、ツール呼び出しの承認（HITL / before_tool_callback）

### Google Cloud: MCP Toolbox for Databases（`googleapis/mcp-toolbox`）

`tools.yaml` に `kind: source`（type: `bigquery` / `cloud-sql-postgres` / `spanner` / `alloydb-postgres` / `firestore`）と `kind: tool`（type: `bigquery-execute-sql` / `bigquery-get-table-info` / `postgres-execute-sql` / `spanner-execute-sql` / `firestore-query` …）を `---` 区切りで宣言。起動は `npx -y @toolbox-sdk/server --stdio --config tools.yaml`、`env` で `GOOGLE_CLOUD_PROJECT` を渡す。BigQuery / Vertex AI Search 等には ADK 1P Toolset もある（公式ドキュメントで対応状況確認）。

ベストプラクティス: スキーマファースト（クエリ前に `get_table_info`）／Instruction で `LIMIT` とカラム指定（処理量課金）／ユーザー入力を SQL に直接埋め込まない／Spanner は `readOnly: true` + `roles/spanner.databaseReader` で二重防御／Firestore は参照と書き込みツールを分け、書き込みは承認後のみ。

推奨 IAM（読み取り / 読み書き）: BigQuery `bigquery.dataViewer` / `dataEditor`、Cloud SQL `cloudsql.viewer` / `editor`、Spanner `spanner.databaseReader` / `databaseUser`、AlloyDB `alloydb.viewer` / `databaseUser`、Firestore `datastore.viewer` / `user`。機密データは VPC Service Controls。

## CLI アプローチ（subprocess ラップ）

MCP サーバーが無い gcloud / kubectl / terraform / 社内 CLI を `FunctionTool` に。**セキュリティ 5 原則**:

1. ホワイトリスト方式（許可サブコマンドを列挙。ブラックリストは漏れる）
2. パラメータ分離（サブコマンド / リソース名 / フラグを別引数で受ける）
3. 入力検証（`^[a-zA-Z0-9_-]+$` 等の正規表現。`--key=value` 形式のみ許可）
4. リスト構築（`subprocess.run([...])`。`shell=True` 禁止、文字列結合しない）
5. タイムアウト（全実行に `timeout=`。超過は `return_code: -1` のエラー dict）

サブコマンドごとに関数を分ける（`kubectl_get` / `kubectl_describe` / `kubectl_logs`）と、型と制約の明示・ツール選択・パラメータ単位の検証・関数レベルのアクセス制御が効く。`secrets` のような漏えいリスクの高いリソースは許可リストから外す。Terraform は `show` / `plan` / `output` まで、`apply` はエージェントにさせずユーザー判断（HITL の実例）。

## MCP vs CLI

| 判断軸 | MCP | CLI |
|---|---|---|
| セットアップ | サーバー選定・接続設定 | 既存 CLI のラップで即時 |
| 構造化 | JSON Schema | Python シグネチャ依存 |
| 再利用 | 言語非依存・複数エージェント共有 | ADK 固有・ライブラリ化が必要 |
| セキュリティ | プロトコルレベル認証 | Python 側で自前バリデーション |
| 保守 | サーバー更新に追従 | CLI 仕様変更でラッパー修正 |

選定フロー: 公式 MCP サーバーあり & 認証要件を満たす → MCP。無い → 社内 CLI/API あり & カスタム MCP 構築コストが妥当なら MCP 構築、そうでなければ CLI。実務は併用（BigQuery MCP + 社内レポート CLI）。

## ツールガバナンス 3 柱

1. **ツールカタログ**: `{type, package, description, required_iam_roles, risk_level, approval_required}` を一覧化
2. **権限マトリクス**: `AGENT_ROLES = {agent: {allowed_tools, denied_tools, max_risk_level}}`（data_analyst は bigquery のみ、sre_operator は gcloud / kubectl / bigquery）
3. **監査ログ**: `before_tool_callback` で `{timestamp, agent_name, tool_name, tool_input, session_id, user_id}` を構造化ログへ

## 関連アンチパターン

God Agent（ツール 10 個超）、Security Afterthought（`execute_sql` / `run_command` / `read_file` を無防備に付与 → 引数サニタイズ + 環境変数 + before_tool_callback）。
