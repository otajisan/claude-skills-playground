"""ツール実行回数制限（第 10 章 10.4.3）。

セッション全体の合計とツール単位の上限を重ねる。LoopAgent.max_iterations /
RunConfig.max_llm_calls / Instruction の終了条件と多重防御で Infinite Loop を防ぐ。

発火順（内側 → 外側）: ループ検知（同一引数 3 回 / 連続空振り MAX_UNPRODUCTIVE_STREAK。どちらも 1 Invocation 内）
→ ツール単位上限 → セッション合計上限 → LLM 呼び出し上限（callbacks.rate_limit_llm_calls）。
直列のツール呼び出しでは 1 往復 = LLM 1 回なので、LLM 上限はツール上限より大きくしないと
ツール層の具体的なエラー文言がモデルに届く前に打ち切られる（config.AgentConfig が警告する）。
"""

from __future__ import annotations

from typing import Any, Optional

from google.adk import Context
from google.adk.tools import BaseTool

from ..config import config

# ループ検知の状態は 1 Invocation 内の暴走を止めるためのもの。temp: スコープに置き、
# 次のユーザー入力には持ち越さない（state_keys.StateKeys のスコープ規約）。
# 同じ質問を数ターン続けて聞き直すのは正当な操作であり、ループではない。
UNPRODUCTIVE_STREAK_PREFIX = "temp:unproductive_"
CALL_HISTORY_KEY = "temp:_call_history"


def is_unproductive(tool_response: Any) -> bool:
    """ツール結果が「進展なし」かを判定する。

    判定できる形だけを見る（判定できなければ False = 進展ありとみなし、誤検知を避ける）:
    - tools.py の規約（status キーあり）: status が success 以外 / total == 0 / results が空リスト
    - MCP（McpToolset が返す CallToolResult の dict 化: content / isError）: isError が真
    - それ以外（status も isError も無い dict、RAG や AgentTool の str・list）: False
    """
    if not isinstance(tool_response, dict):
        return False
    if "status" not in tool_response:
        return tool_response.get("isError") is True
    if tool_response.get("status") != "success":
        return True
    if tool_response.get("total") == 0:
        return True
    results = tool_response.get("results")
    return isinstance(results, list) and not results


class ExecutionLimiter:
    """セッションあたりのツール実行回数を制限する（状態は State に持つ）。

    before_tool_callback に `check_limit`、after_tool_callback に `record_result` を登録する。
    カウンタはこのクラスが唯一の持ち主。二重に登録しない。
    """

    def __init__(
        self,
        max_calls_per_session: int = 50,
        max_calls_per_tool: int = 10,
        loop_window: int = 3,
        max_unproductive_streak: int = 3,
    ) -> None:
        self.max_calls_per_session = max_calls_per_session
        self.max_calls_per_tool = max_calls_per_tool
        self.loop_window = loop_window
        self.max_unproductive_streak = max_unproductive_streak

    @staticmethod
    def _streak_key(tool_name: str) -> str:
        return f"{UNPRODUCTIVE_STREAK_PREFIX}{tool_name}"

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

        # 連続空振り検知: 引数を変えながら同じツールで該当なし / エラーを繰り返すループを止める
        # （同一引数の検知だけでは「パソコン → ノート → PC → laptop …」の再検索をすり抜ける）
        streak = int(state.get(self._streak_key(tool.name), 0))
        if streak >= self.max_unproductive_streak:
            return {
                "status": "error",
                "error": (
                    f"ツール '{tool.name}' の結果が {streak} 回連続で該当なし／エラーでした。"
                    "これ以上の再試行はせず、これまでの結果を踏まえて回答するか、該当なしであることをユーザーに伝えて終了してください。"
                ),
            }

        # ループ検知: 直近 N 回が同一ツール・同一引数なら停止（1 Invocation 内）
        signature = f"{tool.name}:{sorted(args.items()) if isinstance(args, dict) else args}"
        history = list(state.get(CALL_HISTORY_KEY, []))
        history.append(signature)
        history = history[-self.loop_window :]
        state[CALL_HISTORY_KEY] = history
        if len(history) == self.loop_window and len(set(history)) == 1:
            return {"status": "error", "error": "同じ操作が連続して繰り返されています。入力を変えるか、処理を終了してください。"}

        state["_total_tool_calls"] = total + 1
        state[per_tool_key] = per_tool + 1
        return None

    def record_result(self, tool: BaseTool, args: dict, tool_context: Context, tool_response: Any) -> None:
        """after_tool_callback に登録する。記録のみで結果は差し替えない（常に None）。

        ADK は before_tool_callback でスキップされた呼び出しにも after_tool_callback を回すため、
        上限超過 / RBAC 拒否 / 承認待ちのエラー dict もここを通り、空振りとして数える。
        """
        key = self._streak_key(tool.name)
        if is_unproductive(tool_response):
            tool_context.state[key] = int(tool_context.state.get(key, 0)) + 1
        else:
            tool_context.state[key] = 0
        return None


limiter = ExecutionLimiter(
    max_calls_per_session=config.max_tool_calls_per_session,
    max_calls_per_tool=config.max_tool_calls_per_tool,
    max_unproductive_streak=config.max_unproductive_streak,
)
