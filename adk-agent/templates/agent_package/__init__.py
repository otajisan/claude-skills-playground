# ADK はエージェントを Python パッケージとして読み込む。
# adk run / web のローダーは「パッケージの app」→「root_agent」の順に探すため、
# App（Compaction / GlobalInstructionPlugin）を効かせるには app も必ず公開する。
# adk eval / optimize は agent.root_agent を参照するため agent サブモジュールも公開する。
from . import agent as agent
from .agent import app, root_agent

__all__ = ["agent", "app", "root_agent"]
