from __future__ import annotations

from pathlib import Path

from orchestrator.llm import get_llm
from orchestrator.state import BuildPlan, ToolResult
from orchestrator.tools.build import build_image


def run_dockerizer(repo_path: Path, plan: BuildPlan, image_tag: str, retry_limit: int = 2) -> tuple[str, ToolResult]:
    llm = get_llm()
    dockerfile_content = llm.dockerize(plan)
    dockerfile_path = repo_path / "Dockerfile"
    dockerfile_path.write_text(dockerfile_content, encoding="utf-8")

    last_result = ToolResult(ok=False, step="build", details="uninitialized", output="")
    for _ in range(retry_limit + 1):
        last_result = build_image(repo_path, image_tag)
        if last_result.ok:
            return str(dockerfile_path), last_result

    return str(dockerfile_path), last_result
