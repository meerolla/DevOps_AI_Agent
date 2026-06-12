from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from orchestrator.agents.diagnose_fix import apply_fix_for_failure
from orchestrator.agents.dockerizer import run_dockerizer
from orchestrator.agents.planner import run_planner
from orchestrator.audit import append_audit
from orchestrator.state import PipelineState, StepName
from orchestrator.tools.deploy import deploy
from orchestrator.tools.health import healthcheck
from orchestrator.tools.infra import build_infra_plan, provision_infra
from orchestrator.tools.scan import scan_image
from orchestrator.tools.test import run_tests


def approve_infra_gate(state: PipelineState, auto_approve: bool) -> bool:
    if state.approvals.infra:
        return True
    if auto_approve:
        state.approvals.infra = True
        append_audit(state, "approve_infra", "approval", "approved", "auto approved")
        return True

    response = interrupt({"step": "approve_infra", "plan": state.infra_plan or ""})
    approved = bool(response.get("approved")) if isinstance(response, dict) else bool(response)
    state.approvals.infra = approved
    append_audit(state, "approve_infra", "approval", "approved" if approved else "denied", "human gate")
    return approved


def approve_deploy_gate(state: PipelineState, auto_approve: bool) -> bool:
    if state.approvals.deploy:
        return True
    if auto_approve:
        state.approvals.deploy = True
        append_audit(state, "approve_deploy", "approval", "approved", "auto approved")
        return True

    response = interrupt({"step": "approve_deploy", "image": state.image_ref or ""})
    approved = bool(response.get("approved")) if isinstance(response, dict) else bool(response)
    state.approvals.deploy = approved
    append_audit(state, "approve_deploy", "approval", "approved" if approved else "denied", "human gate")
    return approved


def _step_with_retries(
    state: PipelineState,
    step: StepName,
    run_step: Callable[[], tuple[bool, str]],
    repo_path: Path,
) -> bool:
    while True:
        ok, output = run_step()
        append_audit(state, step, "run", "ok" if ok else "failed", output)
        if ok:
            state.mark_step(step, "ok")
            return True

        state.mark_step(step, "failed")
        state.add_retry(step)
        proposal = apply_fix_for_failure(repo_path, step, output)
        append_audit(state, "diagnose_fix", "propose_fix", "ok" if not proposal.escalated else "escalated", proposal.change_summary)

        if proposal.escalated or state.retries.get(step, 0) > state.retry_limit:
            state.mark_step(step, "escalated")
            state.escalate_reason = proposal.root_cause
            return False


def run_pipeline(state: PipelineState, auto_approve: bool | None = None) -> PipelineState:
    auto_approve = auto_approve if auto_approve is not None else os.getenv("AUTO_APPROVE", "0") == "1"
    repo_path = Path(state.repo_ref)

    state.build_plan = run_planner(repo_path)
    state.mark_step("plan", "ok")
    append_audit(state, "plan", "agent", "ok", state.build_plan.model_dump_json())

    image_tag = "ghcr.io/demo/sample:latest"
    dockerfile_ref, build_result = run_dockerizer(repo_path, state.build_plan, image_tag, retry_limit=state.retry_limit)
    state.dockerfile_ref = dockerfile_ref
    if not build_result.ok:
        state.mark_step("build", "escalated")
        append_audit(state, "build", "run", "escalated", build_result.output)
        state.escalate_reason = "docker build failed after bounded retries"
        return state

    state.image_ref = build_result.artifact_ref or image_tag
    state.mark_step("dockerize", "ok")
    state.mark_step("build", "ok")
    append_audit(state, "dockerize", "agent", "ok", f"dockerfile={dockerfile_ref}")
    append_audit(state, "build", "run", "ok", build_result.output)

    def _run_test() -> tuple[bool, str]:
        result = run_tests(repo_path, state.build_plan.test_command)
        state.test_results = result.output
        return result.ok, result.output

    if not _step_with_retries(state, "test", _run_test, repo_path):
        return state

    def _run_scan() -> tuple[bool, str]:
        result = scan_image(repo_path, state.image_ref or image_tag)
        state.scan_report = result.output
        return result.ok, result.output

    if not _step_with_retries(state, "scan", _run_scan, repo_path):
        return state

    state.infra_plan = build_infra_plan("demo", ["ghcr-pull-secret"])
    state.infra_plan_generated = True
    append_audit(state, "approve_infra", "plan", "ok", state.infra_plan)

    if not approve_infra_gate(state, auto_approve):
        state.mark_step("approve_infra", "failed")
        return state
    state.mark_step("approve_infra", "ok")

    provision = provision_infra(
        repo_path=repo_path,
        namespace="demo",
        secret_names=["ghcr-pull-secret"],
        approved=state.approvals.infra,
        plan_generated=state.infra_plan_generated,
    )
    state.mark_step("provision", "ok" if provision.ok else "failed")
    append_audit(state, "provision", "run", "ok" if provision.ok else "failed", provision.output)
    if not provision.ok:
        return state

    if not approve_deploy_gate(state, auto_approve):
        state.mark_step("approve_deploy", "failed")
        return state
    state.mark_step("approve_deploy", "ok")

    deploy_result = deploy(repo_path, state.image_ref or image_tag, "demo", approved=state.approvals.deploy)
    state.manifests_ref = deploy_result.artifact_ref
    state.mark_step("deploy", "ok" if deploy_result.ok else "failed")
    append_audit(state, "deploy", "run", "ok" if deploy_result.ok else "failed", deploy_result.output)
    if not deploy_result.ok:
        return state

    def _run_health() -> tuple[bool, str]:
        result = healthcheck(repo_path)
        return result.ok, result.output

    _step_with_retries(state, "healthcheck", _run_health, repo_path)
    return state


def build_graph() -> StateGraph:
    graph = StateGraph(dict)

    def _pass(state: dict) -> dict:
        return state

    graph.add_node("plan", _pass)
    graph.add_node("dockerize", _pass)
    graph.add_node("build", _pass)
    graph.add_node("test", _pass)
    graph.add_node("scan", _pass)
    graph.add_node("approve_infra", _pass)
    graph.add_node("provision", _pass)
    graph.add_node("approve_deploy", _pass)
    graph.add_node("deploy", _pass)
    graph.add_node("healthcheck", _pass)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "dockerize")
    graph.add_edge("dockerize", "build")
    graph.add_edge("build", "test")
    graph.add_edge("test", "scan")
    graph.add_edge("scan", "approve_infra")
    graph.add_edge("approve_infra", "provision")
    graph.add_edge("provision", "approve_deploy")
    graph.add_edge("approve_deploy", "deploy")
    graph.add_edge("deploy", "healthcheck")
    graph.add_edge("healthcheck", END)
    return graph
