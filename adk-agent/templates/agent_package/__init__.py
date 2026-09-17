# ADK はエージェントを Python パッケージとして読み込む。
# adk run / web / eval / optimize は agent.root_agent（と app）を参照するため、
# agent サブモジュールと root_agent の両方を公開する。
from . import agent as agent
from .agent import root_agent

__all__ = ["agent", "root_agent"]
