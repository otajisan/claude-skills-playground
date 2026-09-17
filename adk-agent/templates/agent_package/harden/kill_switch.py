"""Kill Switch — LLM の判断に依存しないコードレベルの緊急停止（第 10 章 10.4.1）。

4 要件: 即時性 / 確実性 / 粒度（global・agent・tool）/ 復元性。
本番では状態を外部のフィーチャーフラグストア等から読む（ここではプロセス内メモリ）。
"""

from __future__ import annotations

import threading
from typing import Optional

from google.adk import Context
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool
from google.genai import types


class KillSwitch:
    """エージェントの緊急停止機構（スレッドセーフ）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._global_kill = False
        self._agent_kills: set[str] = set()
        self._tool_kills: set[str] = set()

    # --- 操作 ---
    def activate_global(self) -> None:
        with self._lock:
            self._global_kill = True

    def deactivate_global(self) -> None:
        with self._lock:
            self._global_kill = False

    def activate_agent(self, agent_name: str) -> None:
        with self._lock:
            self._agent_kills.add(agent_name)

    def deactivate_agent(self, agent_name: str) -> None:
        with self._lock:
            self._agent_kills.discard(agent_name)

    def activate_tool(self, tool_name: str) -> None:
        with self._lock:
            self._tool_kills.add(tool_name)

    def deactivate_tool(self, tool_name: str) -> None:
        with self._lock:
            self._tool_kills.discard(tool_name)

    def reset(self) -> None:
        with self._lock:
            self._global_kill = False
            self._agent_kills.clear()
            self._tool_kills.clear()

    # --- 判定 ---
    def is_agent_killed(self, agent_name: str) -> bool:
        with self._lock:
            return self._global_kill or agent_name in self._agent_kills

    def is_tool_killed(self, tool_name: str) -> bool:
        with self._lock:
            return self._global_kill or tool_name in self._tool_kills


kill_switch = KillSwitch()


def before_model_kill_switch(callback_context: Context, llm_request: LlmRequest) -> Optional[LlmResponse]:
    """停止中のエージェントは LLM を呼ばず固定応答を返す。合成の最優先に置く。"""
    if kill_switch.is_agent_killed(callback_context.agent_name):
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="現在、このエージェントはメンテナンス中のため利用できません。")],
            )
        )
    return None


def before_tool_kill_switch(tool: BaseTool, args: dict, tool_context: Context) -> Optional[dict]:
    """停止中のツールはエラー dict を返して実行をスキップする。"""
    if kill_switch.is_tool_killed(tool.name):
        return {"status": "error", "error": f"ツール '{tool.name}' はシステム管理者により一時停止されています。"}
    return None
