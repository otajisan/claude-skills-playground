"""HITL 承認フロー（第 5 章 5.5.3）。

before_tool_callback で承認条件に一致するツール呼び出しをブロックし、承認リクエストを State に保存。
before_model_callback でユーザーの「承認: <id>」/「拒否: <id>」を検出してフラグを立て、
次の呼び出しで通す。承認対象ツールは Agent の tools= に登録されていないと発火しない。

承認基準 6 つ（影響範囲 / 可逆性 / 金額 / 権限 / 法的リスク / 前例）のうち金額・ツール名を例示。
非同期承認（Firestore + 通知）やタイムアウト（24h）は本番要件に合わせて拡張する。
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.adk import Context
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool
from google.genai import types

from ..config import config

PENDING_KEY = "_pending_approval"
APPROVAL_TIMEOUT = timedelta(hours=24)
APPROVED_FLAG_TTL = timedelta(minutes=10)  # 承認後、同じ操作を実行するまでの有効期間


@dataclass(frozen=True)
class ApprovalRule:
    condition: Callable[[dict], bool]
    message: str


# TODO: 業務に合わせて承認ルールを定義する
APPROVAL_RULES: dict[str, ApprovalRule] = {
    "delete_record": ApprovalRule(condition=lambda args: True, message="削除は取り消せないため承認が必要です"),
    "transfer_funds": ApprovalRule(
        condition=lambda args: int(args.get("amount", 0)) >= config.approval_amount_threshold * 2,
        message="高額送金のため承認が必要です",
    ),
    "submit_expense": ApprovalRule(
        condition=lambda args: int(args.get("amount", 0)) >= config.approval_amount_threshold,
        message="高額経費のため承認が必要です",
    ),
}


def _approval_flag(tool_name: str) -> str:
    return f"_approval_{tool_name}"


def _args_signature(args: dict) -> str:
    """承認をツール名だけでなく引数にも紐付けるための決定的な署名。"""
    return json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)


def check_approval(tool: BaseTool, args: dict, tool_context: Context) -> Optional[dict]:
    """ツール実行前の承認チェック（before_tool_callback）。"""
    rule = APPROVAL_RULES.get(tool.name)
    if rule is None or not rule.condition(args):
        return None

    flag = _approval_flag(tool.name)
    approved_raw = tool_context.state.get(flag)
    if approved_raw:
        approved = json.loads(approved_raw)
        tool_context.state[flag] = None  # 1 回限りの承認（別引数・期限切れでも消費して再承認を求める）
        if (
            approved.get("args_signature") == _args_signature(args)
            and datetime.fromisoformat(approved["expires_at"]) >= datetime.now(timezone.utc)
        ):
            return None

    request_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)
    tool_context.state[PENDING_KEY] = json.dumps(
        {
            "request_id": request_id,
            "tool_name": tool.name,
            "args": args,
            "args_signature": _args_signature(args),
            "requested_at": now.isoformat(),
            "expires_at": (now + APPROVAL_TIMEOUT).isoformat(),
        },
        ensure_ascii=False,
        default=str,
    )
    return {
        "status": "approval_required",
        "request_id": request_id,
        "message": (
            f"{rule.message}。対象: {tool.name} {json.dumps(args, ensure_ascii=False, default=str)}。"
            f"承認する場合は「承認: {request_id}」、取り消す場合は「拒否: {request_id}」と入力してください。"
        ),
    }


def handle_approval_input(callback_context: Context, llm_request: LlmRequest) -> Optional[LlmResponse]:
    """ユーザーの承認 / 拒否入力を処理する（before_model_callback）。"""
    pending_raw = callback_context.state.get(PENDING_KEY)
    if not pending_raw:
        return None
    pending = json.loads(pending_raw)

    text = ""
    for content in reversed(llm_request.contents or []):
        if content.role == "user" and content.parts:
            text = "".join(p.text or "" for p in content.parts if getattr(p, "text", None))
            break
    if not text:
        return None

    request_id = pending["request_id"]
    if datetime.fromisoformat(pending["expires_at"]) < datetime.now(timezone.utc):
        callback_context.state[PENDING_KEY] = None
        return _fixed(f"承認リクエスト {request_id} は期限切れです。必要であれば操作をやり直してください。")

    if re.search(rf"承認\s*[:：]\s*{re.escape(request_id)}", text):
        callback_context.state[_approval_flag(pending["tool_name"])] = json.dumps(
            {
                "request_id": request_id,
                "args_signature": pending["args_signature"],
                "expires_at": (datetime.now(timezone.utc) + APPROVED_FLAG_TTL).isoformat(),
            }
        )
        callback_context.state[PENDING_KEY] = None
        return _fixed(f"承認されました。{pending['tool_name']} を実行します。続けて操作内容をもう一度お伝えください。")
    if re.search(rf"拒否\s*[:：]\s*{re.escape(request_id)}", text):
        callback_context.state[PENDING_KEY] = None
        return _fixed(f"リクエスト {request_id} を取り消しました。")
    return None


def _fixed(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))
