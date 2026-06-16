from pathlib import Path
import subprocess
import sys

from orchestrator.artifacts import generate_pipeline_artifacts
from orchestrator.state import BuildPlan, PipelineState


def _make_state(tmp_path: Path) -> PipelineState:
    return PipelineState(
        goal="test",
        repo_ref=str(tmp_path),
        cluster="default",
        registry="ghcr.io/demo/sample",
        namespace="my-app",
        app_name="sample",
    )


def test_generated_ci_workflow_has_pr_and_main_tracks(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")

    generate_pipeline_artifacts(state, plan)

    ci_path = tmp_path / ".github" / "workflows" / "ci.yml"
    ci_text = ci_path.read_text(encoding="utf-8")

    assert "pull_request:" in ci_text
    assert "build-and-bump:" in ci_text
    assert "github.event_name == 'push'" in ci_text
    assert "docker/login-action@v3" in ci_text
    assert "helm_values.py set-tag" in ci_text
    assert "[skip ci]" in ci_text


def test_generated_helm_values_helper_updates_tag(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")

    generate_pipeline_artifacts(state, plan)

    helper_path = tmp_path / ".github" / "scripts" / "helm_values.py"
    assert helper_path.exists()

    values_path = tmp_path / "helm" / "values.yaml"
    original = values_path.read_text(encoding="utf-8")
    assert "tag: latest" in original

    subprocess.check_call(
        [
            sys.executable,
            str(helper_path),
            "set-tag",
            "--file",
            str(values_path),
            "--tag",
            "abc123",
        ]
    )

    updated = values_path.read_text(encoding="utf-8")
    assert "tag: abc123" in updated
