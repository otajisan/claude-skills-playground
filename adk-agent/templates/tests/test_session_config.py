"""SessionService / MemoryService 生成と State アクセサのテスト。"""

import importlib

import pytest
from google.adk.sessions import InMemorySessionService

from my_agent import config as config_module
from my_agent import session_config
from my_agent.state_keys import UserState, get_max_results, get_user_role, get_user_tier, load_user_state, save_user_state


def _reload_with_env(monkeypatch, **env):
    """環境変数を設定してから config / session_config を再読み込みする。"""
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    importlib.reload(config_module)
    return importlib.reload(session_config)


class TestCreateSessionService:
    def test_dev_returns_inmemory(self, monkeypatch):
        sc = _reload_with_env(monkeypatch, AGENT_ENV="dev")
        assert isinstance(sc.create_session_service(), InMemorySessionService)

    def test_staging_requires_database_url(self, monkeypatch):
        sc = _reload_with_env(monkeypatch, AGENT_ENV="staging", DATABASE_URL=None)
        with pytest.raises(ValueError, match="DATABASE_URL"):
            sc.create_session_service()

    def test_prod_requires_agent_engine_id(self, monkeypatch):
        sc = _reload_with_env(
            monkeypatch, AGENT_ENV="prod", GOOGLE_CLOUD_PROJECT="p", GOOGLE_CLOUD_LOCATION="us-central1", AGENT_ENGINE_ID=None
        )
        with pytest.raises(ValueError, match="AGENT_ENGINE_ID"):
            sc.create_session_service()

    def test_unknown_env_rejected(self, monkeypatch):
        sc = _reload_with_env(monkeypatch, AGENT_ENV="qa")
        with pytest.raises(ValueError, match="AGENT_ENV"):
            sc.create_session_service()


class TestCreateMemoryService:
    def test_disabled_by_default(self, monkeypatch):
        sc = _reload_with_env(monkeypatch, AGENT_ENV="dev", ENABLE_MEMORY_BANK=None)
        assert sc.create_memory_service() is None

    def test_dev_enabled_uses_inmemory(self, monkeypatch):
        sc = _reload_with_env(monkeypatch, AGENT_ENV="dev", ENABLE_MEMORY_BANK="true")
        assert type(sc.create_memory_service()).__name__ == "InMemoryMemoryService"


class TestConfig:
    def test_default_model_is_explicit_gemini(self, monkeypatch):
        _reload_with_env(monkeypatch, AGENT_MODEL=None)
        assert config_module.config.model == "gemini-3.5-flash"
        assert config_module.build_model() == "gemini-3.5-flash"

    def test_invalid_int_env_raises(self, monkeypatch):
        monkeypatch.setenv("COMPACTION_INTERVAL", "twenty")
        with pytest.raises(ValueError, match="COMPACTION_INTERVAL"):
            importlib.reload(config_module)
        monkeypatch.delenv("COMPACTION_INTERVAL")
        importlib.reload(config_module)


class TestStateKeys:
    def test_tier_and_role_fallback(self):
        assert get_user_tier({"user:tier": "gold"}) == "free"
        assert get_user_tier({"user:tier": "premium"}) == "premium"
        assert get_user_role({}) == "viewer"
        assert get_user_role({"user:role": "root"}) == "viewer"

    def test_max_results_clamped(self):
        assert get_max_results({"app:max_search_results": 500}) == 100
        assert get_max_results({"app:max_search_results": "abc"}) == 5

    def test_user_state_roundtrip(self):
        state = {"user:name": "田中", "user:tier": "premium", "user:role": "editor"}
        user = load_user_state(state)
        assert user == UserState(name="田中", tier="premium", role="editor", preferred_language="ja")
        user.tier = "standard"
        save_user_state(state, user)
        assert state["user:tier"] == "standard"
