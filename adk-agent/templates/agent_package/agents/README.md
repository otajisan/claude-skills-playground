# agents/ — サブエージェントの置き場

規模が大きくなったら `agent.py` は組み立て専用にし、サブエージェントをここに分割する。

```
agent_package/
├── agent.py            # root_agent の組み立てのみ
├── agents/
│   ├── __init__.py
│   ├── researchers.py  # 並列リサーチ（ParallelAgent + output_key）
│   ├── planner.py      # 動的 Instruction で State の調査結果を統合
│   └── reporter.py     # output_schema で構造化出力
├── tools/              # ツールが増えたら分割
├── schemas/models.py   # Pydantic 出力スキーマ（Field(description=)、ネスト 3 層以内）
└── prompts/            # 長い Instruction テンプレート
```

分割の判断基準（references/10-architecture-patterns.md）:

- Instruction を 1〜2 文で説明できない / ツールが 5 個を超えたら分割を検討
- 各サブエージェントは `model=build_model(config.model)` を明示し、`output_key` を衝突しないように付ける
- `ParallelAgent` の子は書き込み先 State キーを分ける
- `LoopAgent` には必ず `max_iterations`
- ネストは 3 層まで。階層がわかる命名にする

例（Sequential + Parallel パイプライン）:

```python
from google.adk import Agent
from google.adk.agents import ParallelAgent, SequentialAgent
from ..config import build_model, config

spot_researcher = Agent(name="spot_researcher", model=build_model(config.model),
                        description="観光スポットを調査する", instruction="...", tools=[...],
                        output_key="spot_research")
# restaurant_researcher / transport_researcher も同様
research_phase = ParallelAgent(name="research_phase", sub_agents=[spot_researcher, ...])
root_agent = SequentialAgent(name="travel_pipeline", sub_agents=[research_phase, schedule_planner, budget_reporter])
```
