"""段階的エスカレーション（第 10 章 10.4.2）。

Level 1 Warning（ログのみ）→ 2 Restricted（高リスクツール拒否・頻度制限）→
3 Stopped（固定応答）→ 4 HITL（オペレーター対応要求）。
低レベルから段階を踏むことで誤検知による過剰停止を避ける。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Optional

from google.adk import Context
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool
from google.genai import types

logger = logging.getLogger(__name__)

HIGH_RISK_TOOLS: set[str] = {"delete_record", "transfer_funds", "execute_sql", "update_user_role"}


class EscalationLevel(IntEnum):
    NORMAL = 0
    WARNING = 1
    RESTRICTED = 2
    STOPPED = 3
    HUMAN_ESCALATION = 4


@dataclass
class UserIncidentTracker:
    user_id: str
    current_level: EscalationLevel = EscalationLevel.NORMAL
    warnings: list[datetime] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class EscalationManager:
    """ユーザーごとのインシデントを追跡し、レベルを昇格 / 解除する。"""

    def __init__(self, warning_to_restrict_threshold: int = 3, warning_window: timedelta = timedelta(minutes=10)) -> None:
        self._lock = threading.Lock()
        self._trackers: dict[str, UserIncidentTracker] = {}
        self.warning_to_restrict_threshold = warning_to_restrict_threshold
        self.warning_window = warning_window

    def get_tracker(self, user_id: str) -> UserIncidentTracker:
        with self._lock:
            return self._trackers.setdefault(user_id, UserIncidentTracker(user_id=user_id))

    def escalate(self, user_id: str, reason: str) -> EscalationLevel:
        """警告を 1 件加算し、ウィンドウ内の警告数が閾値を超えたら RESTRICTED に昇格する。"""
        now = datetime.now(timezone.utc)
        tracker = self.get_tracker(user_id)
        with self._lock:
            tracker.warnings = [t for t in tracker.warnings if now - t <= self.warning_window]
            tracker.warnings.append(now)
            tracker.reasons.append(reason)
            if tracker.current_level < EscalationLevel.WARNING:
                tracker.current_level = EscalationLevel.WARNING
            if len(tracker.warnings) >= self.warning_to_restrict_threshold and tracker.current_level < EscalationLevel.RESTRICTED:
                tracker.current_level = EscalationLevel.RESTRICTED
            logger.warning("エスカレーション", extra={"user_id": user_id, "level": tracker.current_level.name, "reason": reason})
            return tracker.current_level

    def force_stop(self, user_id: str, reason: str) -> None:
        tracker = self.get_tracker(user_id)
        with self._lock:
            tracker.current_level = EscalationLevel.STOPPED
            tracker.reasons.append(reason)

    def escalate_to_human(self, user_id: str, reason: str) -> None:
        tracker = self.get_tracker(user_id)
        with self._lock:
            tracker.current_level = EscalationLevel.HUMAN_ESCALATION
            tracker.reasons.append(reason)

    def resolve(self, user_id: str) -> None:
        """管理者操作で解除する。"""
        with self._lock:
            self._trackers.pop(user_id, None)


escalation_mgr = EscalationManager()


def _fixed(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def escalation_callback(callback_context: Context, llm_request: LlmRequest) -> Optional[LlmResponse]:
    """エスカレーションレベルに基づいてリクエストを制御する（before_model）。"""
    user_id = callback_context.state.get("user_id", "unknown")
    level = escalation_mgr.get_tracker(user_id).current_level
    if level == EscalationLevel.STOPPED:
        return _fixed("セキュリティ上の理由により、現在このサービスはご利用いただけません。")
    if level == EscalationLevel.HUMAN_ESCALATION:
        return _fixed("担当オペレーターにお繋ぎします。しばらくお待ちください。")
    return None


def restricted_tool_callback(tool: BaseTool, args: dict, tool_context: Context) -> Optional[dict]:
    """RESTRICTED 以上のユーザーには高リスクツールを拒否する（before_tool）。"""
    user_id = tool_context.state.get("user_id", "unknown")
    level = escalation_mgr.get_tracker(user_id).current_level
    if level >= EscalationLevel.RESTRICTED and tool.name in HIGH_RISK_TOOLS:
        return {"status": "error", "error": "現在このアカウントでは高リスクな操作が制限されています。管理者にお問い合わせください。"}
    return None
