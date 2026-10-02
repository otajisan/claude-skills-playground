"""State キーの一元管理と型安全なアクセサ（第 4 章 4.3）。

State は dict[str, Any] で型安全性が無いため、
- キーは定数クラスで管理し（プレフィックスを必ず付ける）
- 読み取りはアクセサで許可値に丸め
- 構造化が必要な部分は Pydantic モデルで検証する
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

UserTier = Literal["free", "standard", "premium"]
UserRole = Literal["viewer", "editor", "admin"]


class StateKeys:
    """State キー定数。プレフィックスで寿命を表す。

    app:  アプリ全体（全ユーザー共通の設定）
    user: ユーザー単位・セッション横断
    なし  当該 Session のみ
    temp: 1 Invocation のみ（次の Invocation で消える）
    """

    # app: スコープ
    APP_VERSION = "app:version"
    APP_MAX_RESULTS = "app:max_search_results"

    # user: スコープ
    USER_NAME = "user:name"
    USER_TIER = "user:tier"
    USER_ROLE = "user:role"
    USER_LANGUAGE = "user:preferred_language"
    USER_IMPORTANT_CONTEXT = "user:important_context"  # Compaction で失いたくない値の退避先

    # session スコープ
    SESSION_ID = "session_id"
    USER_ID = "user_id"

    # temp: スコープ
    TEMP_SEARCH_COUNT = "temp:search_count"
    TEMP_CURRENT_INTENT = "temp:current_intent"
    TEMP_LAST_TOOL_RESULT = "temp:last_tool_result"

    # ガードレール内部用（アンダースコア始まりは内部状態の慣習）
    LLM_CALL_COUNT = "_llm_call_count"
    TOTAL_TOOL_CALLS = "_total_tool_calls"
    PENDING_APPROVAL = "_pending_approval"
    INJECTION_DETECTED = "_injection_detected"


def get_user_tier(state: dict[str, Any]) -> UserTier:
    """ユーザーティアを取得する。不正値は free に丸める。"""
    tier = state.get(StateKeys.USER_TIER, "free")
    if tier not in ("free", "standard", "premium"):
        return "free"
    return tier  # type: ignore[return-value]


def get_user_role(state: dict[str, Any]) -> UserRole:
    """ユーザーロールを取得する。不正値は最小権限の viewer に丸める。"""
    role = state.get(StateKeys.USER_ROLE, "viewer")
    if role not in ("viewer", "editor", "admin"):
        return "viewer"
    return role  # type: ignore[return-value]


def get_max_results(state: dict[str, Any], default: int = 5) -> int:
    """検索結果の上限件数を取得する。1〜100 に丸める。"""
    raw = state.get(StateKeys.APP_MAX_RESULTS, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(100, value))


class UserState(BaseModel):
    """ユーザー関連 State の構造化表現。読み込み時にバリデーションされる。"""

    name: str = "ゲスト"
    tier: str = Field(default="free", pattern="^(free|standard|premium)$")
    role: str = Field(default="viewer", pattern="^(viewer|editor|admin)$")
    preferred_language: str = "ja"


def load_user_state(state: dict[str, Any]) -> UserState:
    """State からユーザー情報を構造化して読み込む。"""
    return UserState(
        name=state.get(StateKeys.USER_NAME, "ゲスト"),
        tier=get_user_tier(state),
        role=get_user_role(state),
        preferred_language=state.get(StateKeys.USER_LANGUAGE, "ja"),
    )


def save_user_state(state: dict[str, Any], user: UserState) -> None:
    """UserState を user: スコープの State に書き戻す。"""
    state[StateKeys.USER_NAME] = user.name
    state[StateKeys.USER_TIER] = user.tier
    state[StateKeys.USER_ROLE] = user.role
    state[StateKeys.USER_LANGUAGE] = user.preferred_language
