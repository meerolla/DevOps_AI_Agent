from __future__ import annotations

from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def build_image(repo_path: Path, image_tag: str) -> ToolResult:
    dockerfile = repo_path / "Dockerfile"
    if not dockerfile.exists():
        return ToolResult(ok=False, step="build", details="Dockerfile missing", output="")

    if is_sandbox():
        return ToolResult(
            ok=True,
            step="build",
            details="sandbox build succeeded",
            output="sandbox build",
            artifact_ref=image_tag,
        )

    ok, output = run_command(f"docker build -t {image_tag} .", cwd=repo_path)
    return ToolResult(
        ok=ok,
        step="build",
        details="docker build executed",
        output=output,
        artifact_ref=image_tag if ok else None,
    )
