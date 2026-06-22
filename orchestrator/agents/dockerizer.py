from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.agents.repo_tools import read_repo_file
from orchestrator.llm import get_llm
from orchestrator.state import BuildPlan, ComponentPlan, ToolResult
from orchestrator.tools.build import build_image


def _collect_dockerizer_evidence(repo_path: Path, plan: BuildPlan) -> dict[str, Any]:
    files = sorted(
        str(path.relative_to(repo_path)).replace("\\", "/")
        for path in repo_path.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )

    dependency_files = [name for name in ["requirements.txt", "package.json", "pom.xml", "go.mod"] if name in files]
    dependency_content: dict[str, str] = {}
    for dep in dependency_files:
        dependency_content[dep] = read_repo_file(repo_path, dep)

    entrypoint_file = plan.entrypoint.replace(".", "/") + ".py" if ":" in plan.entrypoint else plan.entrypoint
    entrypoint_content = ""
    entrypoint_exists = False
    if entrypoint_file and entrypoint_file in files:
        entrypoint_content = read_repo_file(repo_path, entrypoint_file)
        entrypoint_exists = True

    return {
        "files": files,
        "dependency_files": dependency_files,
        "dependencies": dependency_content,
        "entrypoint_file": entrypoint_file,
        "entrypoint_exists": entrypoint_exists,
        "entrypoint_content": entrypoint_content,
    }


def _enforce_framework_runtime(plan: BuildPlan, dockerfile_content: str) -> str:
    framework = plan.framework.lower()
    if framework == "fastapi":
        if "http.server" in dockerfile_content or "uvicorn" not in dockerfile_content:
            port = str(plan.ports[0] if plan.ports else 8000)
            entrypoint = plan.entrypoint if plan.entrypoint != "unknown" else "app.main:app"
            lines = [line for line in dockerfile_content.splitlines() if not line.strip().startswith("CMD ")]
            lines.append(f'CMD ["uvicorn", "{entrypoint}", "--host", "0.0.0.0", "--port", "{port}"]')
            return "\n".join(lines) + "\n"
    return dockerfile_content


def _component_build_plan(component: ComponentPlan, fallback: BuildPlan) -> BuildPlan:
    """Build a per-component BuildPlan, inheriting from the repo-level plan where unset."""
    return BuildPlan(
        language=component.language if component.language != "unknown" else fallback.language,
        framework=component.framework if component.framework != "unknown" else fallback.framework,
        entrypoint=component.entrypoint if component.entrypoint != "unknown" else fallback.entrypoint,
        ports=component.ports if component.ports else fallback.ports,
        test_command=component.test_command if component.test_command != "unknown" else fallback.test_command,
        dependencies=fallback.dependencies,
    )


def _write_component_dockerfile(
    repo_path: Path,
    component: ComponentPlan,
    fallback_plan: BuildPlan,
    llm: object,
) -> Path:
    """Write Dockerfile for one component inside its context directory. Returns the path written."""
    comp_plan = _component_build_plan(component, fallback_plan)
    comp_root = repo_path / component.context_path if component.context_path else repo_path
    evidence = _collect_dockerizer_evidence(comp_root, comp_plan)

    if hasattr(llm, "dockerize_from_evidence"):
        content = llm.dockerize_from_evidence(comp_plan, evidence)  # type: ignore[assignment]
    else:
        content = llm.dockerize(comp_plan)  # type: ignore[union-attr]
    content = _enforce_framework_runtime(comp_plan, content)

    dockerfile_path = repo_path / component.dockerfile_path
    dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    dockerfile_path.write_text(content, encoding="utf-8")
    return dockerfile_path


def run_dockerizer(repo_path: Path, plan: BuildPlan, image_tag: str, retry_limit: int = 2) -> tuple[str, ToolResult]:
    llm = get_llm()

    # Multi-component path: write one Dockerfile per component, no build here
    # (building is done per-component in graph._node_build).
    if plan.components:
        written_paths: list[str] = []
        for component in plan.components:
            df_path = _write_component_dockerfile(repo_path, component, plan, llm)
            written_paths.append(str(df_path))
        return written_paths[0], ToolResult(
            ok=True, step="build", details="multi-component dockerize", output="; ".join(written_paths)
        )

    dockerfile_path = repo_path / "Dockerfile"
    evidence = _collect_dockerizer_evidence(repo_path, plan)

    if hasattr(llm, "dockerize_from_evidence"):
        dockerfile_content = llm.dockerize_from_evidence(plan, evidence)  # type: ignore[assignment]
    else:
        dockerfile_content = llm.dockerize(plan)
    dockerfile_content = _enforce_framework_runtime(plan, dockerfile_content)
    dockerfile_path.write_text(dockerfile_content, encoding="utf-8")

    last_result = ToolResult(ok=False, step="build", details="uninitialized", output="")
    for _ in range(retry_limit + 1):
        last_result = build_image(repo_path, image_tag)
        if last_result.ok:
            return str(dockerfile_path), last_result

        if hasattr(llm, "dockerize_from_evidence"):
            dockerfile_content = llm.dockerize_from_evidence(plan, evidence, build_error=last_result.output)  # type: ignore[assignment]
            dockerfile_content = _enforce_framework_runtime(plan, dockerfile_content)
            dockerfile_path.write_text(dockerfile_content, encoding="utf-8")

    return str(dockerfile_path), last_result
