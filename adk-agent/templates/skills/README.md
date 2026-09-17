# ADK Agent Skills（agentskills.io 形式）

`SKILL.md`（frontmatter = L1、本文 = L2）と `references/` `assets/` `scripts/`（L3）で構成し、
`load_skill_from_dir()` → `SkillToolset(skills=[...])` として関数ツールと並列に `tools=` へ登録する。

```python
from pathlib import Path
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
skill_toolset = SkillToolset(skills=[load_skill_from_dir(SKILLS_DIR / "example-skill")])
# Agent(tools=[skill_toolset, get_order_status, cancel_order, ...])
```

設計ルール（references/20-context-engineering.md）: 単一責任 / SKILL.md のツール名と `tools=` を一致 /
破壊的変更はバージョン付きディレクトリ（`example-skill-v2/`）で共存 / `name` はディレクトリ名と一致する kebab-case。
