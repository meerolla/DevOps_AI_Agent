from pathlib import Path

from orchestrator.state import PipelineState
from orchestrator.tools.deploy import deploy
from orchestrator.tools.infra import provision_infra


def test_provision_requires_approval_and_plan(tmp_path: Path) -> None:
    result_no_plan = provision_infra(
        repo_path=tmp_path,
        namespace="demo",
        secret_names=["ghcr-pull-secret"],
        approved=True,
        plan_generated=False,
    )
    assert not result_no_plan.ok
    assert "plan" in result_no_plan.details

    result_no_approval = provision_infra(
        repo_path=tmp_path,
        namespace="demo",
        secret_names=["ghcr-pull-secret"],
        approved=False,
        plan_generated=True,
    )
    assert not result_no_approval.ok
    assert "approval" in result_no_approval.details


def test_deploy_requires_approval(tmp_path: Path) -> None:
    result = deploy(tmp_path, "ghcr.io/demo/sample:latest", "demo", approved=False)
    assert not result.ok
    assert "approval" in result.details


def test_state_defaults_to_no_approvals(tmp_path: Path) -> None:
    state = PipelineState(goal="demo", repo_ref=str(tmp_path))
    assert state.approvals.infra is False
    assert state.approvals.deploy is False
