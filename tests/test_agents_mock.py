import os
import shutil
from pathlib import Path

from orchestrator.agents.diagnose_fix import apply_fix_for_failure
from orchestrator.graph import run_pipeline
from orchestrator.state import BuildPlan, PipelineState


def _make_state(tmp_path: Path, **kwargs) -> PipelineState:
    return PipelineState(
        goal="test",
        repo_ref=str(tmp_path),
        cluster="default",
        registry="ghcr.io/demo/sample",
        namespace="my-app",
        app_name="sample",
        pull_secret_name="ghcr-pull-secret",
        **kwargs,
    )


# ── Boundary invariant: Diagnose-Fix never writes app source code ─────────────

def test_diagnose_fix_test_failure_escalates_never_writes_files(tmp_path: Path) -> None:
    """test failures always escalate; no file in the repo is touched."""
    os.environ["LLM_MODE"] = "mock"
    app_file = tmp_path / "app.py"
    app_file.write_text("def add(a, b): return a - b\n", encoding="utf-8")
    mtime_before = app_file.stat().st_mtime

    state = _make_state(tmp_path)
    state.build_plan = BuildPlan(language="python", test_command="pytest -q")

    proposal = apply_fix_for_failure(tmp_path, "test", "FAILED assert add(2,3)==5", state)

    assert proposal.escalated is True
    assert proposal.fix_type == "escalate"
    assert app_file.stat().st_mtime == mtime_before, "app.py must not be modified"


def test_diagnose_fix_does_not_write_outside_owned_artifacts(tmp_path: Path) -> None:
    """_assert_owned_artifact raises ValueError for any non-artifact path."""
    from orchestrator.agents.diagnose_fix import _assert_owned_artifact
    import pytest

    # allowed paths
    _assert_owned_artifact(tmp_path / "Dockerfile", tmp_path)
    _assert_owned_artifact(tmp_path / "deploy" / "helm" / "values.yaml", tmp_path)
    _assert_owned_artifact(tmp_path / ".github" / "workflows" / "ci.yml", tmp_path)
    _assert_owned_artifact(tmp_path / "deploy" / "argocd" / "application.yaml", tmp_path)

    # disallowed paths
    with pytest.raises(ValueError):
        _assert_owned_artifact(tmp_path / "app.py", tmp_path)
    with pytest.raises(ValueError):
        _assert_owned_artifact(tmp_path / "src" / "main.py", tmp_path)
    with pytest.raises(ValueError):
        _assert_owned_artifact(tmp_path / "requirements.txt", tmp_path)


# ── Per-handler tests ─────────────────────────────────────────────────────────

def test_diagnose_fix_build_failure_regenerates_dockerfile(tmp_path: Path) -> None:
    os.environ["LLM_MODE"] = "mock"
    state = _make_state(tmp_path)
    state.build_plan = BuildPlan(language="python", entrypoint="app.py", test_command="pytest -q")

    proposal = apply_fix_for_failure(tmp_path, "build", "error: RUN pip failed line 3", state)

    assert proposal.escalated is False
    assert proposal.fix_type == "tool_retry"
    assert (tmp_path / "Dockerfile").exists(), "Dockerfile should be regenerated"
    assert not (tmp_path / "app.py").exists(), "app.py must not be created"


def test_diagnose_fix_build_infra_error_escalates(tmp_path: Path) -> None:
    os.environ["LLM_MODE"] = "mock"
    state = _make_state(tmp_path)
    state.build_plan = BuildPlan(language="python")

    proposal = apply_fix_for_failure(
        tmp_path, "build",
        "permission denied while trying to connect to the Docker daemon socket", state
    )

    assert proposal.escalated is True
    assert proposal.fix_type == "infra_hint"
    assert not (tmp_path / "Dockerfile").exists(), "Dockerfile must not be written for infra errors"


def test_diagnose_fix_healthcheck_infra_error_escalates(tmp_path: Path) -> None:
    os.environ["LLM_MODE"] = "mock"
    state = _make_state(tmp_path)

    proposal = apply_fix_for_failure(
        tmp_path, "healthcheck",
        "Pod status: ImagePullBackOff\nBack-off pulling image ghcr.io/demo/sample:latest", state
    )

    assert proposal.escalated is True
    assert proposal.fix_type == "infra_hint"
    assert "ImagePullBackOff" in proposal.root_cause


def test_diagnose_fix_healthcheck_config_error_regenerates_helm(tmp_path: Path) -> None:
    os.environ["LLM_MODE"] = "mock"
    state = _make_state(tmp_path)
    (tmp_path / "helm" / "templates").mkdir(parents=True)

    proposal = apply_fix_for_failure(
        tmp_path, "healthcheck",
        "Deployment resume-scorer not ready after rollout timeout", state
    )

    assert proposal.escalated is False
    assert proposal.fix_type == "config_hint"
    assert (tmp_path / "deploy" / "helm" / "values.yaml").exists()
    assert (tmp_path / "deploy" / "helm" / "templates" / "deployment.yaml").exists()
    assert not (tmp_path / "app.py").exists()


def test_diagnose_fix_deploy_config_error_regenerates_argocd(tmp_path: Path) -> None:
    os.environ["LLM_MODE"] = "mock"
    state = _make_state(tmp_path)

    proposal = apply_fix_for_failure(
        tmp_path, "deploy",
        "Error: chart path ./helm not found\nnamespace my-app not found", state
    )

    assert proposal.escalated is False
    assert proposal.fix_type == "config_hint"
    assert (tmp_path / "deploy" / "argocd" / "application.yaml").exists()
    assert not (tmp_path / "app.py").exists()


def test_diagnose_fix_provision_always_escalates(tmp_path: Path) -> None:
    os.environ["LLM_MODE"] = "mock"
    state = _make_state(tmp_path)

    proposal = apply_fix_for_failure(tmp_path, "provision", "namespace my-app not found", state)

    assert proposal.escalated is True
    assert proposal.fix_type == "infra_hint"
    assert state.namespace in proposal.hint


def test_diagnose_fix_scan_vulnerability_escalates(tmp_path: Path) -> None:
    os.environ["LLM_MODE"] = "mock"
    state = _make_state(tmp_path)

    proposal = apply_fix_for_failure(tmp_path, "scan", "CRITICAL CVE-2024-1234 in libssl", state)

    assert proposal.escalated is True
    assert proposal.fix_type == "escalate"


# ── Full pipeline run: app-code bug escalates correctly ───────────────────────

def test_full_run_mock_sandbox_app_bug_escalates(tmp_path: Path) -> None:
    """Seeded app bug causes test step to escalate. No app code is patched."""
    os.environ["SANDBOX"] = "1"
    os.environ["LLM_MODE"] = "mock"
    os.environ["FORCE_TEST_FAIL"] = "1"

    fixture_repo = Path("tests/fixtures/sample-repo")
    repo_copy = tmp_path / "sample-repo"
    shutil.copytree(fixture_repo, repo_copy)

    original_app = (repo_copy / "app.py").read_text(encoding="utf-8")

    state = PipelineState(
        goal="set up CI/CD and deploy",
        repo_ref=str(repo_copy),
        cluster="default",
        registry="ghcr.io/demo/sample",
        namespace="my-app",
        app_name="sample",
        auto_commit=False,
    )
    final_state = run_pipeline(state, auto_approve=True)

    # test step escalates — app code bugs are the developer's job
    assert final_state.step_status["test"] == "escalated"
    assert final_state.last_fix_proposal is not None
    assert final_state.last_fix_proposal.fix_type == "escalate"

    # app.py is untouched — the boundary is enforced
    assert (repo_copy / "app.py").read_text(encoding="utf-8") == original_app

    # pipeline artifacts were still generated before test ran
    assert (repo_copy / ".github" / "workflows" / "ci.yml").exists()
    assert (repo_copy / ".github" / "workflows" / "ci-self-heal.yml").exists()
    assert (repo_copy / "deploy" / "helm" / "Chart.yaml").exists()
    assert (repo_copy / "deploy" / "argocd" / "application.yaml").exists()

    # audit log contains no secrets
    for entry in final_state.audit:
        assert "ghp_" not in entry.details

    os.environ.pop("FORCE_TEST_FAIL", None)


# ── H5: pipeline-setup.yaml precedence ───────────────────────────────────────

def test_planner_config_overrides_inferred_language(tmp_path: Path) -> None:
    """pipeline-setup.yaml language field overrides what the planner would infer from files."""
    import os
    os.environ["LLM_MODE"] = "mock"

    # Repo has a requirements.txt that would make the mock planner infer python
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    # pipeline-setup.yaml explicitly declares java
    (tmp_path / "pipeline-setup.yaml").write_text("language: java\nframework: springboot\n", encoding="utf-8")

    from orchestrator.agents.planner import run_planner
    plan = run_planner(tmp_path)

    assert plan.language == "java"
    assert plan.framework == "springboot"


def test_planner_config_overrides_test_command(tmp_path: Path) -> None:
    """test_command in pipeline-setup.yaml takes precedence over inference."""
    import os
    os.environ["LLM_MODE"] = "mock"

    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_dummy(): pass\n", encoding="utf-8")
    # Without config, mock would infer "pytest -q"
    (tmp_path / "pipeline-setup.yaml").write_text("test_command: pytest -v --tb=short\n", encoding="utf-8")

    from orchestrator.agents.planner import run_planner
    plan = run_planner(tmp_path)

    assert plan.test_command == "pytest -v --tb=short"


def test_planner_no_config_file_uses_inference(tmp_path: Path) -> None:
    """When pipeline-setup.yaml is absent, inference is used as normal."""
    import os
    os.environ["LLM_MODE"] = "mock"

    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "app" / "main.py").parent.mkdir(parents=True)
    (tmp_path / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    from orchestrator.agents.planner import run_planner
    plan = run_planner(tmp_path)

    assert plan.language == "python"
    assert plan.framework == "fastapi"
