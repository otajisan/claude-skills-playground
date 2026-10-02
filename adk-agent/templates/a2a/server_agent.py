"""A2A サーバー — ADK エージェントを to_a2a() で公開する（第 7 章 7.2.1、7.2.4）。

依存: pip install "google-adk[a2a]==2.2.0" "a2a-sdk>=0.3.24,<0.4.0"（1.x 系は不可）
起動: python server_agent.py  → http://localhost:8001/.well-known/agent-card.json
Cloud Run: PORT / SERVICE_URL 環境変数で Agent Card の url を差し替える。
experimental 警告は ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS=1 で抑制できる。
ビジネスロジック（Agent 定義）は A2A 非依存にし、adk web / Agent Engine にも転用できる形を保つ。
"""

from __future__ import annotations

import os

import uvicorn
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from google.adk import Agent
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.tools import request_input

AGENT_MODEL = os.environ.get("AGENT_MODEL", "gemini-3.5-flash")
PORT = int(os.environ.get("PORT", "8001"))
SERVICE_URL = os.environ.get("SERVICE_URL", f"http://localhost:{PORT}")


def register_expense(date: str, category: str, amount: int, description: str) -> dict:
    """経費データを登録する。

    Args:
        date: 日付（YYYY-MM-DD。例: 2026-07-10）
        category: 交通費 / 会議費 / 接待費 / 消耗品費 / その他 のいずれか
        amount: 金額（円。例: 1280）
        description: 業務目的・補足（例: 客先訪問の移動）

    Returns:
        status と expense_id を含む辞書
    """
    if category not in ("交通費", "会議費", "接待費", "消耗品費", "その他"):
        return {"status": "error", "error": f"カテゴリが不正です: {category}"}
    if amount <= 0:
        return {"status": "error", "error": "金額は 1 円以上で指定してください"}
    return {"status": "registered", "expense_id": f"EXP-{date}-001", "amount": amount}


expense_agent = Agent(
    name="expense_agent",
    model=AGENT_MODEL,
    description="経費データの登録と照会を行う専門エージェント",
    instruction="""あなたは経費精算を処理するエージェントです。
受け取った経費情報を整理し、register_expense ツールで登録してください。
必要な情報（日付・カテゴリ・金額・説明）が不足している場合は、通常の文章で質問して完了せず、
request_input ツールで不足項目を質問してください（A2A では TASK_STATE_INPUT_REQUIRED になります）。
カテゴリは 交通費・会議費・接待費・消耗品費・その他 のいずれかです。""",
    tools=[request_input, register_expense],
)

AGENT_CARD = AgentCard(
    name="経費精算エージェント",
    description="経費データの登録と照会を行う専門エージェント",
    url=SERVICE_URL,
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True),
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[
        AgentSkill(
            id="register-expense",
            name="経費登録",
            description="日付・カテゴリ・金額・説明を受け取り、経費データを登録する",
            tags=["expense", "registration"],
            examples=["2026 年 7 月 10 日の交通費 1280 円を登録してください"],
        ),
    ],
    # 本番: security_schemes / security で OAuth2 / mTLS を宣言し、to_a2a() の app に認証ミドルウェアを追加する
)

app = to_a2a(expense_agent, host="0.0.0.0", port=PORT, agent_card=AGENT_CARD)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
