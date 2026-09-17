"""セキュリティ機構（harden モードで配線を強化する。agent_package 配下に同居し、config を共有する）。

- kill_switch.py       : 緊急停止（global / agent / tool の 3 粒度、スレッドセーフ）
- escalation.py        : 段階的エスカレーション（Level 1〜4）
- execution_limiter.py : セッション / ツール単位の実行回数制限
- approval.py          : HITL 承認フロー（before_tool_callback + before_model_callback）
- audit_logger.py      : PII マスク済み構造化監査ログ

callbacks.py の既定合成に組み込まれているもの: approval / audit_logger / execution_limiter
harden モードで先頭に追加するもの: kill_switch / escalation
  before_model: kill_switch → escalation → [既定: approval.handle_approval_input → rate_limit → injection → inject]
  before_tool : kill_switch → escalation.restricted_tool → [既定: audit → RBAC → approval.check → 引数検証 → limiter]
ExecutionLimiter は唯一のカウンタ。二重に登録しない。
"""
