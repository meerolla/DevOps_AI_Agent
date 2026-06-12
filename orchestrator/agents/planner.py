from __future__ import annotations

from pathlib import Path

from orchestrator.llm import get_llm
from orchestrator.state import BuildPlan


def run_planner(repo_path: Path) -> BuildPlan:
    llm = get_llm()
    return llm.plan_repo(repo_path)
