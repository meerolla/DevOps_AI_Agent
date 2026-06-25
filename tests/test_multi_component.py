"""Tests for multi-component (multi-service) pipeline support."""

from pathlib import Path
import shutil

import pytest

from orchestrator.agents.planner import _detect_components, run_planner
from orchestrator.artifacts import generate_pipeline_artifacts
from orchestrator.state import BuildPlan, ComponentPlan, PipelineState


_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "multi_service_app"


def _copy_fixture(tmp_path: Path) -> Path:
    """Copy the multi-service fixture into tmp_path so tests don't mutate the source."""
    dest = tmp_path / "multi_service_app"
    shutil.copytree(_FIXTURE_DIR, dest)
    return dest


def _make_multi_state(repo_path: Path) -> PipelineState:
    return PipelineState(
        goal="test",
        repo_ref=str(repo_path),
        cluster="default",
        registry="ghcr.io/demo/multi",
        namespace="multi-app",
        app_name="multi-app",
    )


def _make_multi_plan() -> BuildPlan:
    return BuildPlan(
        language="python",
        framework="fastapi",
        entrypoint="main:app",
        ports=[8000],
        test_command="pytest -q",
        components=[
            ComponentPlan(
                name="api",
                language="python",
                framework="fastapi",
                entrypoint="main:app",
                dockerfile_path="services/api/Dockerfile",
                context_path="services/api",
                ports=[8000],
                test_command="pytest -q",
            ),
            ComponentPlan(
                name="worker",
                language="python",
                framework="unknown",
                entrypoint="main.py",
                dockerfile_path="services/worker/Dockerfile",
                context_path="services/worker",
                ports=[],
                test_command="pytest -q",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Planner: component detection
# ---------------------------------------------------------------------------

def test_detect_components_finds_services_with_dockerfiles(tmp_path: Path) -> None:
    """_detect_components must return one ComponentPlan per services/<name>/Dockerfile found."""
    repo = _copy_fixture(tmp_path)
    components = _detect_components(repo)

    assert len(components) == 2
    names = {c.name for c in components}
    assert names == {"api", "worker"}


def test_detect_components_reads_expose_port_from_dockerfile(tmp_path: Path) -> None:
    """_detect_components must populate ComponentPlan.ports from EXPOSE in each Dockerfile."""
    repo = _copy_fixture(tmp_path)
    components = _detect_components(repo)

    by_name = {c.name: c for c in components}
    assert by_name["api"].ports == [8000]
    assert by_name["worker"].ports == [9000]


def test_detect_components_returns_empty_for_single_service_repo(tmp_path: Path) -> None:
    """_detect_components returns empty list when there is no services/ or apps/ layout."""
    # A plain repo with only a top-level Dockerfile
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    components = _detect_components(tmp_path)
    assert components == []


def test_planner_attaches_components_for_multi_service_repo(tmp_path: Path) -> None:
    """run_planner must populate BuildPlan.components for a multi-service layout."""
    repo = _copy_fixture(tmp_path)
    plan = run_planner(repo)

    assert len(plan.components) == 2
    component_names = {c.name for c in plan.components}
    assert component_names == {"api", "worker"}

    for comp in plan.components:
        assert comp.dockerfile_path.endswith("/Dockerfile")
        assert comp.context_path != ""


def test_planner_does_not_add_components_for_single_service_repo(tmp_path: Path) -> None:
    """Single-component repo: BuildPlan.components must be empty (no regression)."""
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    plan = run_planner(tmp_path)
    assert plan.components == []


# ---------------------------------------------------------------------------
# Artifacts: multi-component CI workflow
# ---------------------------------------------------------------------------

def test_multi_component_ci_has_build_step_per_component(tmp_path: Path) -> None:
    """Generated CI workflow must contain a build+push step for each component."""
    repo = _copy_fixture(tmp_path)
    state = _make_multi_state(repo)
    plan = _make_multi_plan()

    generate_pipeline_artifacts(state, plan)

    ci_text = (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Build and push [api]" in ci_text
    assert "Build and push [worker]" in ci_text


def test_multi_component_ci_uses_component_specific_dockerfiles(tmp_path: Path) -> None:
    """Each build step must reference its own Dockerfile path."""
    repo = _copy_fixture(tmp_path)
    state = _make_multi_state(repo)
    plan = _make_multi_plan()

    generate_pipeline_artifacts(state, plan)

    ci_text = (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "services/api/Dockerfile" in ci_text
    assert "services/worker/Dockerfile" in ci_text


def test_multi_component_ci_has_bump_step_per_component(tmp_path: Path) -> None:
    """CI must bump Helm tag for every component after build."""
    repo = _copy_fixture(tmp_path)
    state = _make_multi_state(repo)
    plan = _make_multi_plan()

    generate_pipeline_artifacts(state, plan)

    ci_text = (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Bump Helm image tag [api]" in ci_text
    assert "Bump Helm image tag [worker]" in ci_text
    assert "--component api" in ci_text
    assert "--component worker" in ci_text


# ---------------------------------------------------------------------------
# Artifacts: multi-component Helm chart
# ---------------------------------------------------------------------------

def test_multi_component_helm_has_deployment_per_component(tmp_path: Path) -> None:
    """Helm templates dir must contain deployment-<name>.yaml for each component."""
    repo = _copy_fixture(tmp_path)
    state = _make_multi_state(repo)
    plan = _make_multi_plan()

    generate_pipeline_artifacts(state, plan)

    templates = repo / "deploy" / "helm" / "templates"
    assert (templates / "deployment-api.yaml").exists()
    assert (templates / "deployment-worker.yaml").exists()
    # Must NOT produce the single-component deployment.yaml
    assert not (templates / "deployment.yaml").exists()


def test_multi_component_helm_deployments_use_component_values(tmp_path: Path) -> None:
    """Each deployment template must reference .Values.components.<name>."""
    repo = _copy_fixture(tmp_path)
    state = _make_multi_state(repo)
    plan = _make_multi_plan()

    generate_pipeline_artifacts(state, plan)

    api_text = (repo / "deploy" / "helm" / "templates" / "deployment-api.yaml").read_text(encoding="utf-8")
    assert ".Values.components.api" in api_text

    worker_text = (repo / "deploy" / "helm" / "templates" / "deployment-worker.yaml").read_text(encoding="utf-8")
    assert ".Values.components.worker" in worker_text


def test_multi_component_helm_values_has_components_block(tmp_path: Path) -> None:
    """values.yaml must contain a components: block with an entry per service."""
    repo = _copy_fixture(tmp_path)
    state = _make_multi_state(repo)
    plan = _make_multi_plan()

    generate_pipeline_artifacts(state, plan)

    values_text = (repo / "deploy" / "helm" / "values.yaml").read_text(encoding="utf-8")
    assert "components:" in values_text
    assert "  api:" in values_text
    assert "  worker:" in values_text


# ---------------------------------------------------------------------------
# Regression: single-component path unchanged
"""Add validators import for port mismatch test."""
from orchestrator.validators import validate_generated_artifacts


# ---------------------------------------------------------------------------

def test_validator_skips_port_checks_for_multi_component(tmp_path: Path) -> None:
    """validate_generated_artifacts must not raise port-mismatch errors for multi-component charts."""
    repo = _copy_fixture(tmp_path)
    state = _make_multi_state(repo)
    plan = _make_multi_plan()
    generate_pipeline_artifacts(state, plan)

    errors = validate_generated_artifacts(str(repo))
    port_errors = [e for e in errors if "containerPort" in e or "Port mismatch" in e]
    assert port_errors == [], f"Unexpected port errors for multi-component chart: {port_errors}"


def test_multi_component_values_uses_expose_port(tmp_path: Path) -> None:
    """values.yaml component port must match the EXPOSE in the component's Dockerfile."""
    repo = _copy_fixture(tmp_path)
    state = _make_multi_state(repo)
    plan = run_planner(repo)  # use real planner so EXPOSE is read
    generate_pipeline_artifacts(state, plan)

    values_text = (repo / "deploy" / "helm" / "values.yaml").read_text(encoding="utf-8")
    # api Dockerfile EXPOSEs 8000, worker EXPOSEs 9000
    assert "containerPort: 8000" in values_text
    assert "containerPort: 9000" in values_text


# ---------------------------------------------------------------------------

def test_single_component_artifacts_unchanged(tmp_path: Path) -> None:
    """Single-component plan must still produce deployment.yaml (not deployment-<name>.yaml)."""
    state = PipelineState(
        goal="test",
        repo_ref=str(tmp_path),
        cluster="default",
        registry="ghcr.io/demo/sample",
        namespace="my-app",
        app_name="sample",
    )
    plan = BuildPlan(language="python", test_command="pytest -q")

    generate_pipeline_artifacts(state, plan)

    templates = tmp_path / "deploy" / "helm" / "templates"
    assert (templates / "deployment.yaml").exists()
    assert not list(templates.glob("deployment-*.yaml"))
