"""設定の一元管理（Config Drift 対策）。

モデル名・環境・接続先・閾値はコードに直書きせず、すべて環境変数から読む。
全環境で同一コードベースを使い、振る舞いの違いは設定だけで制御する。

ADK v2.2.0 で検証。差分は `adk --version` と公式リリースノートで確認する。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:  # 設定ミスは早期に明確なエラーで落とす
        raise ValueError(f"{name} は整数で指定してください: {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} は数値で指定してください: {raw!r}") from exc


@dataclass(frozen=True)
class AgentConfig:
    """環境変数から読み込む設定値。"""

    # --- モデル ---
    # 既定は書籍の検証モデル gemini-3.5-flash（Gemini Developer API に無料枠あり）。
    # ADK の暗黙既定（gemini-3-flash-preview）には依存しない。
    # Claude を使う場合: "anthropic/claude-sonnet-5" など（ANTHROPIC_API_KEY 必須・有料。
    # references/models.md の課金・非対応機能を確認してから切り替える）。
    model: str = field(default_factory=lambda: os.environ.get("AGENT_MODEL", "gemini-3.5-flash"))

    # --- 環境 ---
    env: str = field(default_factory=lambda: os.environ.get("AGENT_ENV", "dev"))  # dev / staging / prod
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))

    # --- Compaction（第 4 章 4.4 推奨値: カスタマーサポート 20 / 2）---
    compaction_interval: int = field(default_factory=lambda: _env_int("COMPACTION_INTERVAL", 20))
    compaction_overlap: int = field(default_factory=lambda: _env_int("COMPACTION_OVERLAP", 2))

    # --- ガードレール閾値 ---
    max_llm_calls_per_session: int = field(default_factory=lambda: _env_int("MAX_LLM_CALLS", 10))
    max_tool_calls_per_session: int = field(default_factory=lambda: _env_int("MAX_TOOL_CALLS", 50))
    max_tool_calls_per_tool: int = field(default_factory=lambda: _env_int("MAX_TOOL_CALLS_PER_TOOL", 10))
    cost_limit_usd: float = field(default_factory=lambda: _env_float("COST_LIMIT_USD", 1.0))

    # --- HITL ---
    approval_amount_threshold: int = field(default_factory=lambda: _env_int("APPROVAL_AMOUNT_THRESHOLD", 500_000))

    # --- 外部リソース（未設定なら無効）---
    rag_corpus_id: str | None = field(default_factory=lambda: os.environ.get("RAG_CORPUS_ID") or None)
    enable_memory_bank: bool = field(
        default_factory=lambda: os.environ.get("ENABLE_MEMORY_BANK", "false").lower() == "true"
    )


config = AgentConfig()


def build_model(spec: str | None = None):
    """AGENT_MODEL の値から Agent(model=...) に渡す指定を返す。

    - "gemini-*"                  : 文字列のまま返す（ADK 既定の Gemini 経路）
    - "anthropic/claude-*"        : Anthropic API 直（ANTHROPIC_API_KEY 必須・有料）。
                                    google.adk.models.anthropic_llm.AnthropicLlm を使う。
                                    `pip install "google-adk[extensions]"`（anthropic パッケージ）が必要
    - "vertex-anthropic/claude-*" : Claude on Vertex AI（GOOGLE_CLOUD_PROJECT / LOCATION + ADC・有料）。
                                    google.adk.models.anthropic_llm.Claude を使う
    - "litellm/<provider>/<model>": LiteLLM 経由（`google-adk[extensions]` の litellm が必要）

    文字列 "claude-*" をそのまま Agent に渡すと ADK のレジストリは Vertex AI 経路（Claude）に
    解決する点に注意。経路を明示するため本関数ではプレフィックスで振り分ける。
    ADK v2.2.0 の google.adk.models.anthropic_llm で確認済み。
    """
    spec = spec or config.model
    if spec.startswith("anthropic/"):
        from google.adk.models.anthropic_llm import AnthropicLlm  # 遅延 import（anthropic 未導入環境で落とさない）

        return AnthropicLlm(model=spec.removeprefix("anthropic/"))
    if spec.startswith("vertex-anthropic/"):
        from google.adk.models.anthropic_llm import Claude

        return Claude(model=spec.removeprefix("vertex-anthropic/"))
    if spec.startswith("litellm/"):
        from google.adk.models.lite_llm import LiteLlm

        return LiteLlm(model=spec.removeprefix("litellm/"))
    return spec


def build_summarizer_llm(spec: str | None = None):
    """Compaction の summarizer 用 BaseLlm を返す。

    Gemini 文字列指定なら google.adk.models.Gemini でラップする（LlmEventSummarizer は BaseLlm を要求）。
    メインのエージェントと同系のモデルに揃える（3 系と 2 系の混在を避ける）。
    """
    model = build_model(spec)
    if isinstance(model, str):
        from google.adk.models import Gemini

        return Gemini(model=model)
    return model
