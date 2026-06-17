from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

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


_PLAN_OVERRIDE_KEYS = {"language", "framework", "entrypoint", "ports", "test_command", "stateful", "needs_db"}


def _load_config_overrides(repo_path: Path) -> dict[str, Any]:
    """Load pipeline-setup.yaml and return only the recognised BuildPlan fields.

    Returns an empty dict if the file does not exist or cannot be parsed.
    Precedence: pipeline-setup.yaml > LLM inference (CLI flags are applied upstream).
    """
    config_path = repo_path / "pipeline-setup.yaml"
    if not config_path.exists():
        return {}
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8", errors="replace")) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(raw, dict):
        return {}
    overrides: dict[str, Any] = {}
    for key in _PLAN_OVERRIDE_KEYS:
        if key in raw and raw[key] not in (None, "", "unknown"):
            overrides[key] = raw[key]
    return overrides


def _apply_config_overrides(plan: BuildPlan, overrides: dict[str, Any]) -> BuildPlan:
    """Return a new BuildPlan with config-file fields applied authoritatively."""
    if not overrides:
        return plan
    merged = plan.model_dump()
    merged.update(overrides)
    return BuildPlan.model_validate(merged)


def run_planner(repo_path: Path) -> BuildPlan:
    llm = get_llm()
    config_overrides = _load_config_overrides(repo_path)

    # Provider mode: let the LLM explore the repo via tool calls before deciding.
    # This gives the LLM autonomy to navigate into subdirectories it finds relevant.
    try:
        from orchestrator.llm import ProviderLLM, _normalize_build_plan_payload
        if isinstance(llm, ProviderLLM):
            raw = llm._chat_with_tools(
                system_prompt=(
                    "You are the Planner agent. Explore the repository using the provided tools "
                    "(list_repo_files, read_repo_file) to understand the codebase. "
                    "Once you have enough information, respond with strict JSON matching BuildPlan: "
                    "language, framework, entrypoint, ports, dependencies, stateful, needs_db, "
                    "test_command, notes. Do not include markdown fences — output JSON only."
                ),
                user_prompt=(
                    "Analyse this repository and produce a BuildPlan. "
                    "Start by listing the root directory, then read the files you need."
                ),
                repo_path=repo_path,
            )
            payload = json.loads(raw)
            plan = _normalize_build_plan_payload(payload)
            return _apply_config_overrides(plan, config_overrides)
    except Exception:
        pass  # fall through to evidence-based path

    evidence = _collect_planner_evidence(repo_path)
    if hasattr(llm, "plan_from_evidence"):
        plan = llm.plan_from_evidence(evidence)  # type: ignore[assignment]
        return _apply_config_overrides(plan, config_overrides)
    plan = llm.plan_repo(repo_path)
    return _apply_config_overrides(plan, config_overrides)
