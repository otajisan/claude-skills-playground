"""コールバック群 — Context Engineering とガードレール（第 3 章 3.4、第 5 章 5.4、第 10 章）。

規約: None を返すと処理続行、値（LlmResponse / dict）を返すと差し替え・スキップ。
関心事ごとに関数を分け、compose_* で合成する。順序に意味がある
（Kill Switch → レート制限 → インジェクション検出 → コンテキスト注入）。

ガードレール内で例外が起きた場合は安全側に倒す（ログを残してブロック応答を返す）。
引数名 callback_context / tool_context / llm_request / llm_response は ADK がキーワードで
渡すため変更しない。ADK v2.2.0 で検証。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any, Optional

from google.adk import Context
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool
from google.genai import types

from .config import config
from .harden.approval import check_approval, handle_approval_input
from .harden.audit_logger import audit_after_tool, audit_before_tool
from .harden.execution_limiter import limiter
from .state_keys import StateKeys, get_max_results, get_user_role

logger = logging.getLogger(__name__)

# --- 型エイリアス ---------------------------------------------------------
BeforeModelCallback = Callable[[Context, LlmRequest], Optional[LlmResponse]]
AfterModelCallback = Callable[[Context, LlmResponse], Optional[LlmResponse]]
BeforeToolCallback = Callable[[BaseTool, dict, Context], Optional[dict]]
AfterToolCallback = Callable[[BaseTool, dict, Context, dict], Optional[dict]]


# --- 合成 -----------------------------------------------------------------
def compose_before_model_callbacks(*callbacks: BeforeModelCallback) -> BeforeModelCallback:
    """複数の before_model_callback を順に適用し、最初に非 None を返した時点で早期リターンする。"""

    def composed(callback_context: Context, llm_request: LlmRequest) -> Optional[LlmResponse]:
        for callback in callbacks:
            try:
                result = callback(callback_context, llm_request)
            except Exception:  # noqa: BLE001 - ガードレールの障害は安全側（ブロック）に倒す
                logger.exception("before_model_callback でエラー: %s", getattr(callback, "__name__", callback))
                return _text_response("一時的なエラーが発生しました。しばらくしてから再度お試しください。")
            if result is not None:
                return result
        return None

    return composed


def compose_after_model_callbacks(*callbacks: AfterModelCallback) -> AfterModelCallback:
    """after_model_callback の合成。差し替えが起きたら以降のコールバックにはその応答を渡す。"""

    def composed(callback_context: Context, llm_response: LlmResponse) -> Optional[LlmResponse]:
        current = llm_response
        replaced = False
        for callback in callbacks:
            try:
                result = callback(callback_context, current)
            except Exception:  # noqa: BLE001
                logger.exception("after_model_callback でエラー: %s", getattr(callback, "__name__", callback))
                return _text_response("応答の検証中にエラーが発生しました。再度お問い合わせください。")
            if result is not None:
                current, replaced = result, True
        return current if replaced else None

    return composed


def compose_before_tool_callbacks(*callbacks: BeforeToolCallback) -> BeforeToolCallback:
    """before_tool_callback の合成。最初に dict を返したコールバックでツール実行をスキップする。"""

    def composed(tool: BaseTool, args: dict, tool_context: Context) -> Optional[dict]:
        for callback in callbacks:
            try:
                result = callback(tool, args, tool_context)
            except Exception:  # noqa: BLE001
                logger.exception("before_tool_callback でエラー: %s", getattr(callback, "__name__", callback))
                return {"status": "error", "error": "ツール実行前の検査でエラーが発生したため実行を中止しました。"}
            if result is not None:
                return result
        return None

    return composed


def compose_after_tool_callbacks(*callbacks: AfterToolCallback) -> AfterToolCallback:
    """after_tool_callback の合成。加工結果を次のコールバックに引き渡す。"""

    def composed(tool: BaseTool, args: dict, tool_context: Context, tool_response: dict) -> Optional[dict]:
        current = tool_response
        replaced = False
        for callback in callbacks:
            try:
                result = callback(tool, args, tool_context, current)
            except Exception:  # noqa: BLE001
                logger.exception("after_tool_callback でエラー: %s", getattr(callback, "__name__", callback))
                return {"status": "error", "error": "ツール結果の検証中にエラーが発生しました。"}
            if result is not None:
                current, replaced = result, True
        return current if replaced else None

    return composed


# --- ヘルパー -------------------------------------------------------------
def _text_response(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _last_user_text(llm_request: LlmRequest) -> str:
    """最新のユーザー発話テキストを取り出す。"""
    for content in reversed(llm_request.contents or []):
        if content.role == "user" and content.parts:
            return "".join(part.text or "" for part in content.parts if getattr(part, "text", None))
    return ""


def _response_text(llm_response: LlmResponse) -> str:
    if not llm_response.content or not llm_response.content.parts:
        return ""
    return "".join(part.text or "" for part in llm_response.content.parts if getattr(part, "text", None))


# --- L1: before_model -----------------------------------------------------
# インジェクションの代表パターン（第一防御線。難読化は LLM 分類器で補う）
INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(指示|命令|ルール).{0,10}(無視|忘れ|リセット|上書き)"),
    re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|rules)", re.IGNORECASE),
    re.compile(r"(システムプロンプト|system\s*prompt).{0,10}(出力|表示|教え|見せ|reveal|show|print)", re.IGNORECASE),
    re.compile(r"\bjailbreak\b|developer\s+mode", re.IGNORECASE),
    re.compile(r"\bDAN\b"),  # 大文字のみ（人名 "Dan" を誤検出しない）
    re.compile(r"(管理者|admin)\s*モード.{0,6}(切り替え|移行|有効)"),
]


def detect_prompt_injection(callback_context: Context, llm_request: LlmRequest) -> Optional[LlmResponse]:
    """プロンプトインジェクションの兆候を検出したら LLM を呼ばずにブロック応答を返す。"""
    text = _last_user_text(llm_request)
    if not text:
        return None
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            callback_context.state[StateKeys.INJECTION_DETECTED] = True
            logger.warning("プロンプトインジェクションを検出", extra={"pattern": pattern.pattern})
            return _text_response("そのリクエストには対応できません。ご質問の内容をもう少し具体的にお教えください。")
    return None


def rate_limit_llm_calls(callback_context: Context, llm_request: LlmRequest) -> Optional[LlmResponse]:
    """セッションあたりの LLM 呼び出し回数を制限する（暴走・コスト防止）。"""
    count = int(callback_context.state.get(StateKeys.LLM_CALL_COUNT, 0)) + 1
    callback_context.state[StateKeys.LLM_CALL_COUNT] = count
    if count > config.max_llm_calls_per_session:
        return _text_response("このセッションでの処理回数が上限に達しました。新しいセッションで再度お試しください。")
    return None


def inject_runtime_context(callback_context: Context, llm_request: LlmRequest) -> Optional[LlmResponse]:
    """State にある動的コンテキスト（例: 退避した重要情報）を LLM リクエストに注入する。"""
    important = callback_context.state.get(StateKeys.USER_IMPORTANT_CONTEXT)
    if important:
        llm_request.append_instructions([f"## Current Context\n{important}"])
    return None


# --- L5: after_model ------------------------------------------------------
PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b0\d{1,4}-\d{1,4}-\d{3,4}\b"), "[PHONE]"),
    (re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b"), "[CARD]"),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "[API_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[API_KEY]"),
]
PROHIBITED_WORDS = ("パスワード", "クレジットカード番号", "シークレット")


def mask_pii(text: str) -> tuple[str, bool]:
    """PII を置換し、置換が発生したかを返す。"""
    masked = text
    for pattern, placeholder in PII_PATTERNS:
        masked = pattern.sub(placeholder, masked)
    return masked, masked != text


def validate_response(callback_context: Context, llm_response: LlmResponse) -> Optional[LlmResponse]:
    """LLM 応答のテキスト部分だけを検査・マスクする。

    function_call など非テキストの parts は保持する（差し替えでツール呼び出しを潰さない）。
    """
    if not llm_response.content or not llm_response.content.parts:
        return None
    new_parts = []
    changed = False
    for part in llm_response.content.parts:
        text = getattr(part, "text", None)
        if not text:
            new_parts.append(part)
            continue
        if any(word in text for word in PROHIBITED_WORDS):
            new_parts.append(types.Part(text="申し訳ございません。セキュリティ上の理由からお伝えできません。"))
            changed = True
            continue
        masked, masked_changed = mask_pii(text)
        new_parts.append(types.Part(text=masked) if masked_changed else part)
        changed = changed or masked_changed
    if not changed:
        return None
    return llm_response.model_copy(
        update={"content": types.Content(role=llm_response.content.role or "model", parts=new_parts)}
    )


# --- L3: before_tool ------------------------------------------------------
# ツール名 → 実行に必要なロール。未登録ツールは全員許可（必要なら明示的に登録する）
TOOL_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "search_items": ("viewer", "editor", "admin"),
    "get_record": ("viewer", "editor", "admin"),
    "update_record": ("editor", "admin"),
    "delete_record": ("admin",),
}


def authorize_tool_access(tool: BaseTool, args: dict, tool_context: Context) -> Optional[dict]:
    """ロールベースでツール実行を許可 / 拒否する。"""
    required = TOOL_PERMISSIONS.get(tool.name)
    if not required:
        return None
    role = get_user_role(tool_context.state)
    if role not in required:
        return {
            "status": "error",
            "error": f"権限不足です。{tool.name} の実行には {'/'.join(required)} のいずれかのロールが必要です。",
        }
    return None


def limit_tool_calls(tool: BaseTool, args: dict, tool_context: Context) -> Optional[dict]:
    """セッション全体・ツール単位の実行回数上限とループ検知（harden.execution_limiter に委譲。カウンタは 1 つ）。"""
    return limiter.check_limit(tool, args, tool_context)


def validate_tool_args(tool: BaseTool, args: dict, tool_context: Context) -> Optional[dict]:
    """引数の基本検証（パストラバーサル・危険な SQL）。"""
    path = args.get("path") or args.get("file_path")
    if isinstance(path, str) and (".." in path or path.startswith("/")):
        return {"status": "error", "error": "指定されたパスにはアクセスできません。"}
    # SQL の検査は SQL を受けるツール（引数名 sql、またはツール名に sql/query を含む）に限定する。
    # search_items(query=...) のような自由文キーワードには適用しない
    sql = args.get("sql")
    if sql is None and re.search(r"sql|query", tool.name, re.IGNORECASE):
        sql = args.get("query")
    if isinstance(sql, str) and re.search(r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE)\b", sql, re.IGNORECASE):
        return {"status": "error", "error": "安全でないクエリが検出されました。読み取り専用のクエリのみ実行できます。"}
    return None


# --- L4: after_tool -------------------------------------------------------
TOOL_RESULT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\[SYSTEM\]", re.IGNORECASE),
    re.compile(r"<\|im_start\|>\s*system", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?(previous|above)\s+instructions", re.IGNORECASE),
]


def _sanitize_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        sanitized = value
        for pattern in TOOL_RESULT_PATTERNS:
            sanitized = pattern.sub("[FILTERED]", sanitized)
        sanitized, _ = mask_pii(sanitized)
        return sanitized, sanitized != value
    if isinstance(value, dict):
        changed = False
        out = {}
        for k, v in value.items():
            out[k], c = _sanitize_value(v)
            changed = changed or c
        return out, changed
    if isinstance(value, list):
        changed = False
        out = []
        for v in value:
            nv, c = _sanitize_value(v)
            out.append(nv)
            changed = changed or c
        return out, changed
    return value, False


def sanitize_tool_result(tool: BaseTool, args: dict, tool_context: Context, tool_response: dict) -> Optional[dict]:
    """ツール結果から間接インジェクションの制御マーカーと PII を除去する。変更があった場合のみ返す。"""
    if not isinstance(tool_response, dict):
        return None
    sanitized, changed = _sanitize_value(tool_response)
    return sanitized if changed else None


def trim_tool_result(tool: BaseTool, args: dict, tool_context: Context, tool_response: dict) -> Optional[dict]:
    """大きな検索結果を上位 N 件に絞りコンテキストを節約する（N は app:max_search_results、既定 5）。"""
    if not isinstance(tool_response, dict):
        return None
    limit = get_max_results(tool_context.state)
    results = tool_response.get("results")
    if isinstance(results, list) and len(results) > limit:
        trimmed = dict(tool_response)
        trimmed["results"] = results[:limit]
        trimmed["note"] = f"全 {len(results)} 件中、上位 {limit} 件を表示"
        return trimmed
    return None


# --- 既定の合成 -----------------------------------------------------------
# 監査ログ・HITL 承認・実行回数制限は harden/ の実装を既定で配線する（原則 5: 新規は FULL_HITL から）。
# harden モードでは Kill Switch / Escalation を先頭に追加する（harden/__init__.py の順序を参照）。
default_before_model = compose_before_model_callbacks(
    handle_approval_input,  # 「承認: <id>」/「拒否: <id>」の入力を先に処理する
    rate_limit_llm_calls,
    detect_prompt_injection,
    inject_runtime_context,
)
default_after_model = compose_after_model_callbacks(validate_response)
default_before_tool = compose_before_tool_callbacks(
    audit_before_tool,
    authorize_tool_access,  # RBAC で拒否されるものは承認フローに進めない
    check_approval,         # APPROVAL_RULES に一致すれば承認待ちにする
    validate_tool_args,
    limit_tool_calls,       # 拒否された呼び出しを数えないよう最後に置く
)
default_after_tool = compose_after_tool_callbacks(audit_after_tool, sanitize_tool_result, trim_tool_result)
