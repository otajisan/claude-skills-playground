"""セキュリティ機構（harden モードで配線を強化する。agent_package 配下に同居し、config を共有する）。

- kill_switch.py       : 緊急停止（global / agent / tool の 3 粒度、スレッドセーフ）
- escalation.py        : 段階的エスカレーション（Level 1〜4）
- execution_limiter.py : セッション / ツール単位の実行回数制限
- approval.py          : HITL 承認フロー（before_tool_callback + before_model_callback）
- audit_logger.py      : PII マスク済み構造化監査ログ

callbacks.py の合成に組み込む順序（先頭ほど優先）:
  before_model: kill_switch → escalation → approval.handle_approval_input → 既定（rate_limit → injection → inject）
  before_tool : kill_switch → audit → RBAC → approval.check → 引数検証 → execution_limiter（既定で配線済み）
ExecutionLimiter は callbacks.default_before_tool にも使われる唯一のカウンタ。二重に登録しない。
"""
