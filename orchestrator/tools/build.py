from __future__ import annotations

import os
from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def build_image(
    repo_path: Path,
    image_tag: str,
    *,
    dockerfile_rel: str = "Dockerfile",
    context_rel: str = ".",
) -> ToolResult:
    """Build and push a Docker image.

    For single-component repos ``dockerfile_rel`` and ``context_rel`` are left at their defaults
    (``Dockerfile`` and ``.``).  For multi-service repos pass the component's paths relative to
    ``repo_path``, e.g. ``dockerfile_rel="services/api/Dockerfile"`` and
    ``context_rel="services/api"``.
    """
    dockerfile = repo_path / dockerfile_rel
    if not dockerfile.exists():
        return ToolResult(ok=False, step="build", details=f"Dockerfile missing: {dockerfile_rel}", output="")

    if is_sandbox():
        return ToolResult(
            ok=True,
            step="build",
            details="sandbox build succeeded",
            output="sandbox build",
            artifact_ref=image_tag,
            test_artifact_ref=f"{image_tag}-test",
        )

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GHCR_TOKEN")
    if token:
        login_ok, login_output = run_command(
            f"echo {token} | docker login ghcr.io -u oauth2 --password-stdin",
            cwd=repo_path,
        )
        if not login_ok:
            return ToolResult(ok=False, step="build", details="docker login failed", output=login_output)

    ok, output = run_command(
        f"docker build -f {dockerfile_rel} -t {image_tag} {context_rel}",
        cwd=repo_path,
    )
    if not ok:
        return ToolResult(
            ok=False,
            step="build",
            details="docker build executed",
            output=output,
            artifact_ref=None,
        )

    # Build the test stage image (local only — not pushed)
    test_tag = f"{image_tag}-test"
    test_ok, test_output = run_command(
        f"docker build -f {dockerfile_rel} --target test -t {test_tag} {context_rel}",
        cwd=repo_path,
    )
    output = f"{output}\n{test_output}"
    if not test_ok:
        # Non-fatal: single-stage Dockerfile won't have AS test — fall back to runtime image for tests
        test_tag = image_tag

    push_ok, push_output = run_command(f"docker push {image_tag}", cwd=repo_path)
    output = f"{output}\n{push_output}"
    return ToolResult(
        ok=push_ok,
        step="build",
        details="docker build/push executed",
        output=output,
        artifact_ref=image_tag if push_ok else None,
        test_artifact_ref=test_tag if push_ok else None,
    )
