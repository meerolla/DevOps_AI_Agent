from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.agents.repo_tools import list_repo_files, read_repo_file
from orchestrator.llm import get_llm
from orchestrator.state import BuildPlan


_DEPENDENCY_FILES = [
    "pipeline-setup.yaml",
    "requirements.txt",
    "package.json",
    "pom.xml",
    "build.gradle",
    "go.mod",
    "Gemfile",
]

_ENTRYPOINT_CANDIDATES = [
    "app/main.py",
    "main.py",
    "app.py",
    "src/index.js",
    "index.js",
    "server.js",
]


def _collect_planner_evidence(repo_path: Path) -> dict[str, Any]:
    root_entries = list_repo_files(repo_path, ".")
    files = sorted(
        str(path.relative_to(repo_path)).replace("\\", "/")
        for path in repo_path.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )

    dependencies: dict[str, str] = {}
    for file_name in _DEPENDENCY_FILES:
        if file_name in files:
            dependencies[file_name] = read_repo_file(repo_path, file_name)

    entrypoint_files: dict[str, str] = {}
    for file_name in _ENTRYPOINT_CANDIDATES:
        if file_name in files:
            entrypoint_files[file_name] = read_repo_file(repo_path, file_name)

    return {
        "root_entries": root_entries,
        "files": files,
        "dependencies": dependencies,
        "entrypoint_files": entrypoint_files,
    }


def run_planner(repo_path: Path) -> BuildPlan:
    llm = get_llm()
    evidence = _collect_planner_evidence(repo_path)
    if hasattr(llm, "plan_from_evidence"):
        return llm.plan_from_evidence(evidence)  # type: ignore[no-any-return]
    return llm.plan_repo(repo_path)
