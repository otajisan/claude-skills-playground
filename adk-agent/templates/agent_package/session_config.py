"""SessionService / MemoryService を環境に応じて生成する（第 4 章 4.2、4.5）。

ADK の「プラグイン可能なバックエンド」により、エージェントコードを変えずに
dev（InMemory）/ staging（Database）/ prod（Vertex AI）を切り替える。
必須環境変数が無い場合はフォールバックせず ValueError で明確に落とす。
"""

from __future__ import annotations

import os

from google.adk.sessions import BaseSessionService, InMemorySessionService

from .config import config


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"AGENT_ENV={config.env} では環境変数 {name} が必須です。")
    return value


def create_session_service() -> BaseSessionService:
    """AGENT_ENV に応じた SessionService を返す。

    - dev     : InMemorySessionService（プロセス終了で消える。ローカル・pytest 専用）
    - staging : DatabaseSessionService（DATABASE_URL。例: postgresql+asyncpg://... / sqlite+aiosqlite:///x.db）
    - prod    : VertexAiSessionService（GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION / AGENT_ENGINE_ID）
    """
    env = config.env
    if env == "dev":
        return InMemorySessionService()
    if env == "staging":
        from google.adk.sessions import DatabaseSessionService  # google-adk[db] が必要

        return DatabaseSessionService(db_url=_require("DATABASE_URL"))
    if env == "prod":
        from google.adk.sessions import VertexAiSessionService

        return VertexAiSessionService(
            project=_require("GOOGLE_CLOUD_PROJECT"),
            location=_require("GOOGLE_CLOUD_LOCATION"),
            agent_engine_id=_require("AGENT_ENGINE_ID"),
        )
    raise ValueError(f"未知の AGENT_ENV です: {env!r}（dev / staging / prod）")


def create_memory_service():
    """ENABLE_MEMORY_BANK に応じた MemoryService を返す。

    - 無効（既定）: None（Memory 層なしで動作する。開発時の安全な既定）
    - 有効 + dev  : InMemoryMemoryService（挙動確認用）
    - 有効 + それ以外: VertexAiMemoryBankService（有料。事前に Agent Engine / Memory Bank を作成）
    """
    if not config.enable_memory_bank:
        return None
    if config.env == "dev":
        from google.adk.memory import InMemoryMemoryService

        return InMemoryMemoryService()
    from google.adk.memory import VertexAiMemoryBankService

    return VertexAiMemoryBankService(
        project=_require("GOOGLE_CLOUD_PROJECT"),
        location=_require("GOOGLE_CLOUD_LOCATION"),
        agent_engine_id=_require("AGENT_ENGINE_ID"),
    )
