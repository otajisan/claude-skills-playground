"""harden/ のセキュリティ機構のユニットテスト（正常通過と検出の両方）。

harden/ は agent_package（scaffold 後は my_agent/）配下に同居する。
"""

from unittest.mock import MagicMock

from google.adk.models import LlmRequest
from google.genai import types

from my_agent.harden.approval import PENDING_KEY, check_approval, handle_approval_input
from my_agent.harden.audit_logger import audit_before_tool, mask_pii
from my_agent.harden.escalation import EscalationLevel, EscalationManager, escalation_callback, escalation_mgr, restricted_tool_callback
from my_agent.harden.execution_limiter import ExecutionLimiter
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
