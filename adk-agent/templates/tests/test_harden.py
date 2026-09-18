"""harden/ のセキュリティ機構のユニットテスト（正常通過と検出の両方）。

harden/ は agent_package（scaffold 後は my_agent/）配下に同居する。
"""

from unittest.mock import MagicMock

import pytest
from google.adk.models import LlmRequest
from google.genai import types

from my_agent.harden.approval import PENDING_KEY, check_approval, handle_approval_input
from my_agent.harden.audit_logger import audit_before_tool, mask_pii
from my_agent.harden.escalation import EscalationLevel, EscalationManager, escalation_callback, escalation_mgr, restricted_tool_callback
from my_agent.harden.execution_limiter import ExecutionLimiter, is_unproductive
from my_agent.harden.kill_switch import before_model_kill_switch, before_tool_kill_switch, kill_switch


def _ctx(state: dict, agent_name: str = "my_agent") -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    ctx.agent_name = agent_name
    return ctx


def _tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    return tool


def _request(text: str) -> LlmRequest:
    return LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text=text)])])


class TestKillSwitch:
    def setup_method(self):
        kill_switch.reset()

    def test_normal_passes(self):
        assert before_model_kill_switch(_ctx({}), _request("hi")) is None
        assert before_tool_kill_switch(_tool("get_record"), {}, _ctx({})) is None

    def test_agent_kill_blocks_model(self):
        kill_switch.activate_agent("my_agent")
        result = before_model_kill_switch(_ctx({}), _request("hi"))
        assert result is not None and "メンテナンス" in result.content.parts[0].text
        assert before_model_kill_switch(_ctx({}, agent_name="other"), _request("hi")) is None

    def test_global_kill_blocks_tools(self):
        kill_switch.activate_global()
        assert before_tool_kill_switch(_tool("get_record"), {}, _ctx({}))["status"] == "error"
        kill_switch.deactivate_global()
        assert before_tool_kill_switch(_tool("get_record"), {}, _ctx({})) is None


class TestEscalation:
    def test_warning_then_restricted(self):
        mgr = EscalationManager(warning_to_restrict_threshold=3)
        assert mgr.escalate("u1", "a") == EscalationLevel.WARNING
        assert mgr.escalate("u1", "b") == EscalationLevel.WARNING
        assert mgr.escalate("u1", "c") == EscalationLevel.RESTRICTED

    def test_stopped_user_gets_fixed_response(self):
        escalation_mgr.resolve("u2")
        assert escalation_callback(_ctx({"user_id": "u2"}), _request("hi")) is None
        escalation_mgr.force_stop("u2", "test")
        result = escalation_callback(_ctx({"user_id": "u2"}), _request("hi"))
        assert result is not None and "ご利用いただけません" in result.content.parts[0].text
        escalation_mgr.resolve("u2")

    def test_restricted_user_denied_high_risk_tool(self):
        escalation_mgr.resolve("u3")
        for _ in range(3):
            escalation_mgr.escalate("u3", "suspicious")
        assert restricted_tool_callback(_tool("delete_record"), {}, _ctx({"user_id": "u3"}))["status"] == "error"
        assert restricted_tool_callback(_tool("get_record"), {}, _ctx({"user_id": "u3"})) is None
        escalation_mgr.resolve("u3")


class TestExecutionLimiter:
    def test_limits(self):
        limiter = ExecutionLimiter(max_calls_per_session=3, max_calls_per_tool=2, loop_window=3)
        state: dict = {}
        assert limiter.check_limit(_tool("a"), {"x": 1}, _ctx(state)) is None
        assert limiter.check_limit(_tool("a"), {"x": 2}, _ctx(state)) is None
        assert "上限" in limiter.check_limit(_tool("a"), {"x": 3}, _ctx(state))["error"]  # per-tool
        assert limiter.check_limit(_tool("b"), {}, _ctx(state)) is None
        assert "上限" in limiter.check_limit(_tool("c"), {}, _ctx(state))["error"]  # per-session

    def test_loop_detected(self):
        limiter = ExecutionLimiter(max_calls_per_session=50, max_calls_per_tool=50, loop_window=3)
        state: dict = {}
        assert limiter.check_limit(_tool("a"), {"q": "same"}, _ctx(state)) is None
        assert limiter.check_limit(_tool("a"), {"q": "same"}, _ctx(state)) is None
        assert "繰り返され" in limiter.check_limit(_tool("a"), {"q": "same"}, _ctx(state))["error"]

    def test_unproductive_streak_blocks_varying_args(self):
        """引数を変えながら空振りを続けるループ（同一引数検知をすり抜ける実例）を止める。"""
        limiter = ExecutionLimiter(max_calls_per_session=50, max_calls_per_tool=50, max_unproductive_streak=3)
        state: dict = {}
        ctx = _ctx(state)
        empty = {"status": "success", "results": [], "total": 0}
        for query in ("パソコン", "ノート", "PC"):
            assert limiter.check_limit(_tool("search"), {"q": query}, ctx) is None
            assert limiter.record_result(_tool("search"), {"q": query}, ctx, empty) is None
        blocked = limiter.check_limit(_tool("search"), {"q": "laptop"}, ctx)
        assert "連続" in blocked["error"]
        assert "該当なし" in blocked["error"]  # モデルに次の行動（結果を踏まえて回答 / 該当なしを伝える）を示す
        # 別ツールは巻き込まれない
        assert limiter.check_limit(_tool("other"), {}, ctx) is None

    def test_unproductive_streak_resets_on_productive_result(self):
        limiter = ExecutionLimiter(max_calls_per_session=50, max_calls_per_tool=50, max_unproductive_streak=2)
        state: dict = {}
        ctx = _ctx(state)
        empty = {"status": "success", "results": [], "total": 0}
        hit = {"status": "success", "results": [{"id": "ITEM-001"}], "total": 1}
        limiter.record_result(_tool("search"), {"q": "a"}, ctx, empty)
        limiter.record_result(_tool("search"), {"q": "b"}, ctx, hit)
        limiter.record_result(_tool("search"), {"q": "c"}, ctx, empty)
        assert limiter.check_limit(_tool("search"), {"q": "d"}, ctx) is None  # 1 回分しか溜まっていない

    def test_unproductive_streak_is_temp_scoped(self):
        """連続空振りは 1 Invocation 内の暴走なので temp: スコープに置き、次のユーザー入力では持ち越さない。"""
        limiter = ExecutionLimiter()
        state: dict = {}
        limiter.record_result(_tool("search"), {}, _ctx(state), {"status": "error", "error": "x"})
        streak_keys = [k for k in state if "unproductive" in k]
        assert streak_keys and all(k.startswith("temp:") for k in streak_keys)

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            ({"status": "success", "results": [], "total": 0}, True),
            ({"status": "success", "results": []}, True),
            ({"status": "success", "total": 0}, True),
            ({"status": "error", "error": "見つかりません"}, True),
            ({"status": "approval_required"}, True),
            ({"status": "success", "results": [{"id": 1}], "total": 1}, False),
            ({"status": "success", "record": {"id": "REC-100"}}, False),
            # status 規約に従わないツール（MCP / RAG / AgentTool）は判定できる形だけ見る。誤検知で正常なツールを止めない
            ({"content": [{"type": "text", "text": "ok"}], "isError": False}, False),  # MCP 正常
            ({"content": [{"type": "text", "text": "boom"}], "isError": True}, True),  # MCP エラー
            ({"content": []}, False),  # MCP・isError 無し
            ({"result": "RAG の要約テキスト"}, False),  # ADK が非 dict 戻り値を包んだ形
            ("not a dict", False),
            (["chunk1", "chunk2"], False),
        ],
    )
    def test_is_unproductive(self, response, expected):
        assert is_unproductive(response) is expected

    def test_mcp_like_tool_is_not_blocked_after_successes(self):
        """status キーを持たない MCP ツールの正常応答 3 回で 4 回目が止まってはいけない（誤検知防止）。"""
        limiter = ExecutionLimiter(max_calls_per_session=50, max_calls_per_tool=50, max_unproductive_streak=3)
        state: dict = {}
        ctx = _ctx(state)
        mcp_ok = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        for i in range(3):
            assert limiter.check_limit(_tool("mcp_read"), {"i": i}, ctx) is None
            limiter.record_result(_tool("mcp_read"), {"i": i}, ctx, mcp_ok)
        assert limiter.check_limit(_tool("mcp_read"), {"i": 3}, ctx) is None

    def test_identical_args_history_is_temp_scoped(self):
        """同一引数ループの履歴も 1 Invocation 内。同じ質問を数ターン聞き直してもループ扱いしない。"""
        limiter = ExecutionLimiter(loop_window=3)
        state: dict = {}
        limiter.check_limit(_tool("a"), {"q": "same"}, _ctx(state))
        assert all(k.startswith("temp:") for k in state if "history" in k)


class TestApproval:
    def test_non_target_tool_passes(self):
        assert check_approval(_tool("get_record"), {}, _ctx({})) is None

    def test_condition_not_met_passes(self):
        assert check_approval(_tool("submit_expense"), {"amount": 3000}, _ctx({})) is None

    def test_approval_roundtrip(self):
        state: dict = {}
        blocked = check_approval(_tool("submit_expense"), {"amount": 800_000}, _ctx(state))
        assert blocked["status"] == "approval_required"
        request_id = blocked["request_id"]
        assert state[PENDING_KEY]

        # 無関係な入力では何も起きない
        assert handle_approval_input(_ctx(state), _request("ところで天気は？")) is None
        # 承認 → フラグが立つ
        result = handle_approval_input(_ctx(state), _request(f"承認: {request_id}"))
        assert result is not None and "承認されました" in result.content.parts[0].text
        assert state["_approval_submit_expense"]
        # 別引数では通らず、再承認を求める（フラグは消費される）
        other = check_approval(_tool("submit_expense"), {"amount": 900_000}, _ctx(state))
        assert other["status"] == "approval_required" and state["_approval_submit_expense"] is None
        handle_approval_input(_ctx(state), _request(f"承認: {other['request_id']}"))
        # 同じ引数なら通り、フラグは消費される
        assert check_approval(_tool("submit_expense"), {"amount": 900_000}, _ctx(state)) is None
        assert state["_approval_submit_expense"] is None

    def test_rejection(self):
        state: dict = {}
        blocked = check_approval(_tool("delete_record"), {"record_id": "REC-1"}, _ctx(state))
        result = handle_approval_input(_ctx(state), _request(f"拒否: {blocked['request_id']}"))
        assert "取り消しました" in result.content.parts[0].text
        assert state[PENDING_KEY] is None


class TestAudit:
    def test_mask_and_log(self, caplog):
        assert mask_pii("taro@example.com 03-1234-5678") == "[EMAIL] [PHONE]"
        ctx = _ctx({})
        ctx.session.id = "sess-1"
        ctx.user_id = "user-9"
        with caplog.at_level("INFO", logger="audit"):
            assert audit_before_tool(_tool("get_record"), {"email": "taro@example.com"}, ctx) is None
        assert "[EMAIL]" in caplog.text and "example.com" not in caplog.text
        assert "sess-1" in caplog.text and "user-9" in caplog.text
