"""pytest 共通設定。

テストはプロジェクトルート（agent_package の親）から `python -m pytest tests/` で実行する。
import は相対形式ではなく `my_agent.callbacks` のようなパッケージ名で書く。
LLM は呼ばないので API キーは不要（MagicMock で Context を代用）。
"""

import os

import pytest

# .env の Vertex 用プレースホルダで落ちないように、テスト中は API キー経路を強制する
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
os.environ.setdefault("AGENT_ENV", "dev")


@pytest.fixture
def state() -> dict:
    """State の代用 dict（Context の state は dict ライクに get / setitem できる）。"""
    return {"user:role": "viewer", "user:tier": "free"}
