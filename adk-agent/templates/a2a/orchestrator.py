"""Hub-Spoke オーケストレーター — RemoteA2aAgent を AgentTool で包む（第 7 章 7.2.3、7.3.1）。

親が途中結果（経費 ID・金額）を受け取って次のリモートエージェント（承認）を呼ぶため、
sub_agents ではなく AgentTool として tools= に公開する。単一委譲で完結するなら sub_agents でよい。
起動: Spoke（8001 / 8002）を先に起動 → adk web ./orchestrator
"""

from __future__ import annotations

import os

from google.adk import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.tools import AgentTool

AGENT_MODEL = os.environ.get("AGENT_MODEL", "gemini-3.5-flash")
EXPENSE_CARD_URL = os.environ.get("EXPENSE_AGENT_CARD_URL", "http://localhost:8001/.well-known/agent-card.json")
APPROVAL_CARD_URL = os.environ.get("APPROVAL_AGENT_CARD_URL", "http://localhost:8002/.well-known/agent-card.json")

expense_remote = RemoteA2aAgent(
    name="expense_agent",
    description="経費の登録と照会を行う専門エージェント",
    agent_card=EXPENSE_CARD_URL,  # URL / AgentCard オブジェクト / ローカルファイルパスのいずれか
)
approval_remote = RemoteA2aAgent(
    name="approval_agent",
    description="経費 ID と申請理由を受け取り、承認ルールに基づいて判定する専門エージェント",
    agent_card=APPROVAL_CARD_URL,
)

root_agent = Agent(
    name="orchestrator",
    model=AGENT_MODEL,
    description="経費精算業務を専門エージェントに振り分けるオーケストレーター",
    instruction="""ユーザーのリクエストに応じて、対応する専門エージェントに処理を委譲してください。
- 経費の登録・照会 → expense_agent
- 承認申請・承認状況 → approval_agent
複合リクエスト（登録して承認申請まで）は、expense_agent の結果（経費 ID・金額）を確認してから
approval_agent を呼び出してください。エージェントがエラーを返した場合は原因と復旧方法を伝えてください。
専門エージェントの結果は数値・ID を確認してからユーザーに伝えてください（Blind Delegation を避ける）。""",
    tools=[AgentTool(agent=expense_remote), AgentTool(agent=approval_remote)],
)
