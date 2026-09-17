"""ツール実行回数制限（第 10 章 10.4.3）。

セッション全体の合計とツール単位の上限を重ねる。LoopAgent.max_iterations /
RunConfig.max_llm_calls / Instruction の終了条件と多重防御で Infinite Loop を防ぐ。
"""

from __future__ import annotations

from typing import Optional

from google.adk import Context
from google.adk.tools import BaseTool


class ExecutionLimiter:
    """セッションあたりのツール実行回数を制限する（状態は State に持つ）。"""

    def __init__(self, max_calls_per_session: int = 50, max_calls_per_tool: int = 10, loop_window: int = 3) -> None:
        self.max_calls_per_session = max_calls_per_session
        self.max_calls_per_tool = max_calls_per_tool
        self.loop_window = loop_window

    def check_limit(self, tool: BaseTool, args: dict, tool_context: Context) -> Optional[dict]:
        """before_tool_callback に登録する。上限超過・ループ検知でエラー dict を返す。"""
        state = tool_context.state
        total = int(state.get("_total_tool_calls", 0))
        if total >= self.max_calls_per_session:
            return {"status": "error", "error": f"セッションあたりのツール実行上限（{self.max_calls_per_session} 回）に達しました。"}

        per_tool_key = f"_tool_calls_{tool.name}"
        per_tool = int(state.get(per_tool_key, 0))
        if per_tool >= self.max_calls_per_tool:
            return {"status": "error", "error": f"ツール '{tool.name}' の呼び出し回数が上限（{self.max_calls_per_tool} 回）に達しました。"}

        # ループ検知: 直近 N 回が同一ツール・同一引数なら停止
        signature = f"{tool.name}:{sorted(args.items()) if isinstance(args, dict) else args}"
        history = list(state.get("_call_history", []))
        history.append(signature)
        history = history[-self.loop_window :]
        state["_call_history"] = history
        if len(history) == self.loop_window and len(set(history)) == 1:
            return {"status": "error", "error": "同じ操作が連続して繰り返されています。入力を変えるか、処理を終了してください。"}

        state["_total_tool_calls"] = total + 1
        state[per_tool_key] = per_tool + 1
        return None


limiter = ExecutionLimiter()
