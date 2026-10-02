"""監査ログ（第 10 章 10.5.1）。全コールバックで記録のみ行い、処理は続行する。

記録項目: 識別（session_id / user_id / agent_name / trace_id）、入力（マスク済み）、
LLM 呼び出し、ツール実行（マスク済み引数）。PII マスクが漏れると監査ログ自体がリスクになる。
Cloud Logging へは標準 logging の JSON 出力がそのまま収集される（構造化ログ）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from google.adk import Context
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool

logger = logging.getLogger("audit")
logger.setLevel(logging.INFO)
JST = timezone(timedelta(hours=9))

PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b0\d{1,4}-\d{1,4}-\d{3,4}\b"), "[PHONE]"),
    (re.compile(r"\b\d{3}-\d{4}\b"), "[ZIPCODE]"),
    (re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b"), "[CARD]"),
]


def mask_pii(text: str) -> str:
    for pattern, placeholder in PII_PATTERNS:
        text = pattern.sub(placeholder, text)
    return text


def generate_trace_id(session_id: str, timestamp: str) -> str:
    return hashlib.sha256(f"{session_id}:{timestamp}".encode()).hexdigest()[:16]


def identity(ctx: Context) -> tuple[str, str]:
    """Context から session_id / user_id を取る。ADK は ctx.session.id / ctx.user_id を持つ。State の値で上書き可。"""
    session = getattr(ctx, "session", None)
    session_id = ctx.state.get("session_id") or getattr(session, "id", None) or "unknown"
    user_id = ctx.state.get("user_id") or getattr(ctx, "user_id", None) or "unknown"
    return str(session_id), str(user_id)


def _emit(event: str, ctx: Context, **fields: Any) -> None:
    now = datetime.now(JST).isoformat()
    session_id, user_id = identity(ctx)
    entry = {
        "event": event,
        "timestamp": now,
        "trace_id": generate_trace_id(session_id, now),
        "session_id": session_id,
        "user_id": user_id,
        "agent_name": ctx.agent_name,
        **fields,
    }
    logger.info(json.dumps(entry, ensure_ascii=False, default=str))


def audit_before_model(callback_context: Context, llm_request: LlmRequest) -> Optional[LlmResponse]:
    user_input = ""
    for content in reversed(llm_request.contents or []):
        if content.role == "user" and content.parts:
            user_input = "".join(p.text or "" for p in content.parts if getattr(p, "text", None))
            break
    _emit("llm_request", callback_context, user_input_masked=mask_pii(user_input), content_count=len(llm_request.contents or []))
    return None


def audit_after_model(callback_context: Context, llm_response: LlmResponse) -> Optional[LlmResponse]:
    text = ""
    if llm_response.content and llm_response.content.parts:
        text = "".join(p.text or "" for p in llm_response.content.parts if getattr(p, "text", None))
    usage = getattr(llm_response, "usage_metadata", None)
    _emit(
        "llm_response",
        callback_context,
        response_length=len(text),  # 内容は記録しない（長さのみ）
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
    )
    return None


def audit_before_tool(tool: BaseTool, args: dict, tool_context: Context) -> Optional[dict]:
    _emit("tool_call", tool_context, tool_name=tool.name, tool_args_masked=mask_pii(json.dumps(args, ensure_ascii=False, default=str)))
    return None


def audit_after_tool(tool: BaseTool, args: dict, tool_context: Context, tool_response: dict) -> Optional[dict]:
    status = tool_response.get("status") if isinstance(tool_response, dict) else None
    _emit("tool_result", tool_context, tool_name=tool.name, status=status)
    return None
