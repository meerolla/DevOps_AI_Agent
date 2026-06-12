from pathlib import Path

from orchestrator.main import _save_state
from orchestrator.state import PipelineState
from orchestrator.tools.deploy import deploy
from orchestrator.tools.infra import provision_infra


def test_provision_requires_approval_and_plan(tmp_path: Path) -> None:
    result_no_plan = provision_infra(
        repo_path=tmp_path,
        cluster="default",
        namespace="demo",
        secret_names=["ghcr-pull-secret"],
        approved=True,
        plan_generated=False,
    )
    assert not result_no_plan.ok
    assert "plan" in result_no_plan.details

    result_no_approval = provision_infra(
        repo_path=tmp_path,
        cluster="default",
        namespace="demo",
        secret_names=["ghcr-pull-secret"],
        approved=False,
        plan_generated=True,
    )
    assert not result_no_approval.ok
    assert "approval" in result_no_approval.details


def test_deploy_requires_approval(tmp_path: Path) -> None:
    result = deploy(
        repo_path=tmp_path,
        image_ref="ghcr.io/demo/sample:latest",
        namespace="demo",
        cluster="default",
        app_name="sample",
        approved=False,
    )
    assert not result.ok
    assert "approval" in result.details


def test_state_defaults_to_no_approvals(tmp_path: Path) -> None:
    state = PipelineState(goal="demo", repo_ref=str(tmp_path))
    assert state.approvals.infra is False
    assert state.approvals.deploy is False


def test_state_persistence_for_pause(tmp_path: Path) -> None:
    state = PipelineState(goal="demo", repo_ref=str(tmp_path), paused_for="approve_infra")
    state_path = _save_state(state)
    assert state_path.exists()


def test_retry_from_step_resets_escalated_state(tmp_path: Path) -> None:
    state = PipelineState(goal="demo", repo_ref=str(tmp_path))
    # Simulate pipeline that escalated at test
    state.step_status["plan"] = "ok"
    state.step_status["dockerize"] = "ok"
    state.step_status["build"] = "ok"
    state.step_status["test"] = "escalated"
    state.escalate_reason = "Test failure requires developer attention"
    state.retries["test"] = 2

    state.retry_from_step("test")

    # steps before test are preserved
    assert state.step_status["plan"] == "ok"
    assert state.step_status["build"] == "ok"
    # test and all subsequent steps are reset
    for step in ["test", "scan", "approve_infra", "provision", "approve_deploy", "deploy", "healthcheck"]:
        assert state.step_status[step] == "pending"
    assert state.escalate_reason is None
    assert state.retries.get("test") is None
