from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from orchestrator.agents.diagnose_fix import apply_fix_for_failure
from orchestrator.agents.dockerizer import run_dockerizer
from orchestrator.agents.planner import run_planner
from orchestrator.artifacts import generate_pipeline_artifacts
from orchestrator.audit import append_audit
from orchestrator.gitops import auto_commit_generated_artifacts, create_draft_pr_for_generated_artifacts, set_github_repo_variables
from orchestrator.state import PipelineState, StepName
from orchestrator.tools.build import build_image
from orchestrator.tools.deploy import deploy
from orchestrator.tools.health import healthcheck
from orchestrator.tools.infra import build_infra_plan, provision_infra
from orchestrator.tools.scan import scan_image
from orchestrator.tools.test import run_tests
from orchestrator.validators import validate_generated_artifacts


class OrchestratorGraphState(TypedDict):
    pipeline_state: PipelineState
    auto_approve: bool
    phase: Literal["full", "bootstrap", "activate"]


def _node_plan(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]
    repo_path = Path(pipeline_state.repo_ref)

    if pipeline_state.step_status["plan"] != "ok":
        pipeline_state.build_plan = run_planner(repo_path)
        pipeline_state.mark_step("plan", "ok")
        append_audit(pipeline_state, "plan", "agent", "ok", pipeline_state.build_plan.model_dump_json())
    return state


def _node_dockerize(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]
    repo_path = Path(pipeline_state.repo_ref)

    if pipeline_state.step_status["dockerize"] != "ok":
        generated = generate_pipeline_artifacts(pipeline_state, pipeline_state.build_plan)
        append_audit(
            pipeline_state,
            "dockerize",
            "generate_artifacts",
            "ok",
            ",".join(str(p.relative_to(repo_path)).replace("\\", "/") for p in generated),
        )
    return state


def _component_image_tag(state: PipelineState, component_name: str) -> str:
    """Derive a per-component image tag from the top-level registry string."""
    base = state.registry.rsplit(":", 1)[0]  # strip any existing :tag suffix
    return f"{base}-{component_name}:latest"


def _node_build(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]
    repo_path = Path(pipeline_state.repo_ref)
    plan = pipeline_state.build_plan

    image_tag = pipeline_state.image_ref_for_registry()
    if pipeline_state.step_status["build"] != "ok":
        dockerfile_ref, dockerize_result = run_dockerizer(
            repo_path,
            plan,
            image_tag,
            retry_limit=pipeline_state.retry_limit,
        )
        pipeline_state.dockerfile_ref = dockerfile_ref

        # Multi-component: run_dockerizer only wrote Dockerfiles; build each image now.
        if plan and plan.components:
            all_ok = True
            for component in plan.components:
                comp_tag = _component_image_tag(pipeline_state, component.name)
                comp_result = build_image(
                    repo_path,
                    comp_tag,
                    dockerfile_rel=component.dockerfile_path,
                    context_rel=component.context_path or ".",
                )
                if not comp_result.ok:
                    pipeline_state.mark_step("build", "escalated")
                    append_audit(
                        pipeline_state, "build", "run", "escalated",
                        f"component={component.name} | {comp_result.output}",
                    )
                    pipeline_state.escalate_reason = f"docker build failed for component {component.name}"
                    all_ok = False
                    break
                component.image_ref = comp_result.artifact_ref or comp_tag
                component.test_image_ref = comp_result.test_artifact_ref or component.image_ref
                append_audit(pipeline_state, "build", "run", "ok",
                             f"component={component.name} image={component.image_ref}")
            if not all_ok:
                return state
            # Use the first component as the "primary" for state.image_ref (ArgoCD/healthcheck)
            pipeline_state.image_ref = plan.components[0].image_ref
            pipeline_state.test_image_ref = plan.components[0].test_image_ref
        else:
            # Single-component: run_dockerizer already called build_image internally
            if not dockerize_result.ok:
                pipeline_state.mark_step("build", "escalated")
                append_audit(pipeline_state, "build", "run", "escalated", dockerize_result.output)
                pipeline_state.escalate_reason = "docker build failed after bounded retries"
                return state
            pipeline_state.image_ref = dockerize_result.artifact_ref or image_tag
            pipeline_state.test_image_ref = dockerize_result.test_artifact_ref or pipeline_state.image_ref

        pipeline_state.mark_step("dockerize", "ok")
        pipeline_state.mark_step("build", "ok")
        append_audit(pipeline_state, "dockerize", "agent", "ok", f"dockerfile={dockerfile_ref}")
        append_audit(pipeline_state, "build", "run", "ok", dockerize_result.output)
    return state


def _node_test(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]
    repo_path = Path(pipeline_state.repo_ref)
    plan = pipeline_state.build_plan

    def _run_test() -> tuple[bool, str]:
        # Multi-component: run tests for each component in turn; all must pass.
        if plan and plan.components:
            all_output: list[str] = []
            for component in plan.components:
                result = run_tests(
                    repo_path,
                    component.test_command if component.test_command != "unknown" else plan.test_command,
                    image_ref=component.image_ref or None,
                    test_image_ref=component.test_image_ref or None,
                    require_tests=pipeline_state.require_tests,
                )
                all_output.append(f"[{component.name}] {result.output}")
                if not result.ok:
                    pipeline_state.test_results = "\n".join(all_output)
                    return False, "\n".join(all_output)
            output = "\n".join(all_output)
            pipeline_state.test_results = output
            return True, output

        result = run_tests(
            repo_path,
            plan.test_command if plan else "unknown",
            image_ref=pipeline_state.image_ref,
            test_image_ref=pipeline_state.test_image_ref,
            require_tests=pipeline_state.require_tests,
        )
        pipeline_state.test_results = result.output
        return result.ok, result.output

    if pipeline_state.step_status["test"] != "ok":
        _step_with_retries(pipeline_state, "test", _run_test, repo_path)
    return state


def _node_scan(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]
    repo_path = Path(pipeline_state.repo_ref)
    plan = pipeline_state.build_plan
    image_tag = pipeline_state.image_ref_for_registry()

    def _run_scan() -> tuple[bool, str]:
        # Multi-component: scan each image; all must pass.
        if plan and plan.components:
            all_output: list[str] = []
            for component in plan.components:
                result = scan_image(repo_path, component.image_ref or image_tag)
                all_output.append(f"[{component.name}] {result.output}")
                if not result.ok:
                    pipeline_state.scan_report = "\n".join(all_output)
                    return False, "\n".join(all_output)
            output = "\n".join(all_output)
            pipeline_state.scan_report = output
            return True, output

        result = scan_image(repo_path, pipeline_state.image_ref or image_tag)
        pipeline_state.scan_report = result.output
        return result.ok, result.output

    if pipeline_state.step_status["scan"] != "ok":
        _step_with_retries(pipeline_state, "scan", _run_scan, repo_path)
    return state


def _node_approve_infra(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]

    if pipeline_state.step_status["approve_infra"] != "ok":
        pipeline_state.infra_plan = build_infra_plan(pipeline_state.namespace, [pipeline_state.pull_secret_name])
        pipeline_state.infra_plan_generated = True
        append_audit(pipeline_state, "approve_infra", "plan", "ok", pipeline_state.infra_plan)

        if approve_infra_gate(pipeline_state, state["auto_approve"]):
            pipeline_state.mark_step("approve_infra", "ok")
    return state


def _node_provision(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]
    repo_path = Path(pipeline_state.repo_ref)

    if pipeline_state.step_status["provision"] != "ok":
        provision = provision_infra(
            repo_path=repo_path,
            cluster=pipeline_state.cluster,
            namespace=pipeline_state.namespace,
            secret_names=[pipeline_state.pull_secret_name],
            approved=pipeline_state.approvals.infra,
            plan_generated=pipeline_state.infra_plan_generated,
        )
        pipeline_state.mark_step("provision", "ok" if provision.ok else "failed")
        append_audit(pipeline_state, "provision", "run", "ok" if provision.ok else "failed", provision.output)
        if not provision.ok and not pipeline_state.escalate_reason:
            pipeline_state.escalate_reason = f"provision failed: {provision.details}"
    return state


def _node_approve_deploy(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]
    if pipeline_state.step_status["approve_deploy"] != "ok":
        if approve_deploy_gate(pipeline_state, state["auto_approve"]):
            pipeline_state.mark_step("approve_deploy", "ok")
    return state


def _node_deploy(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]
    repo_path = Path(pipeline_state.repo_ref)
    image_tag = pipeline_state.image_ref_for_registry()

    if pipeline_state.step_status["deploy"] != "ok":
        deploy_result = deploy(
            repo_path=repo_path,
            image_ref=pipeline_state.image_ref or image_tag,
            namespace=pipeline_state.namespace,
            cluster=pipeline_state.cluster,
            app_name=pipeline_state.app_name,
            approved=pipeline_state.approvals.deploy,
        )
        pipeline_state.manifests_ref = deploy_result.artifact_ref
        pipeline_state.mark_step("deploy", "ok" if deploy_result.ok else "failed")
        append_audit(pipeline_state, "deploy", "run", "ok" if deploy_result.ok else "failed", deploy_result.output)
        if not deploy_result.ok and not pipeline_state.escalate_reason:
            pipeline_state.escalate_reason = f"deploy failed: {deploy_result.details}"
    return state


def _node_healthcheck(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]
    repo_path = Path(pipeline_state.repo_ref)

    def _run_health() -> tuple[bool, str]:
        result = healthcheck(repo_path, pipeline_state.cluster, pipeline_state.namespace, pipeline_state.app_name)
        return result.ok, result.output

    if pipeline_state.step_status["healthcheck"] != "ok":
        _step_with_retries(pipeline_state, "healthcheck", _run_health, repo_path)
    return state


def _node_finalize(state: OrchestratorGraphState) -> OrchestratorGraphState:
    pipeline_state = state["pipeline_state"]
    repo_path = Path(pipeline_state.repo_ref)

    if pipeline_state.auto_commit and not pipeline_state.commit_sha:
        generated = generate_pipeline_artifacts(pipeline_state, pipeline_state.build_plan)

        validation_errors = validate_generated_artifacts(str(repo_path))
        if validation_errors:
            details = "\n".join(validation_errors)
            append_audit(pipeline_state, "deploy", "artifact_validation", "failed", details)
            proposal = apply_fix_for_failure(repo_path, "deploy", details, pipeline_state)
            pipeline_state.last_fix_proposal = proposal
            append_audit(
                pipeline_state,
                "diagnose_fix",
                "artifact_validation_fix",
                "ok" if not proposal.escalated else "escalated",
                f"fix_type={proposal.fix_type} | {proposal.change_summary}",
            )
            if proposal.escalated:
                pipeline_state.escalate_reason = "artifact validation failed"
                return state

            generated = generate_pipeline_artifacts(pipeline_state, pipeline_state.build_plan)
            validation_errors = validate_generated_artifacts(str(repo_path))
            if validation_errors:
                details = "\n".join(validation_errors)
                append_audit(pipeline_state, "deploy", "artifact_validation", "failed", details)
                pipeline_state.escalate_reason = "artifact validation failed after retry"
                return state

        append_audit(pipeline_state, "deploy", "artifact_validation", "ok", "all checks passed")

        gh_var_warnings = set_github_repo_variables(
            repo_path, pipeline_state.cluster, pipeline_state.namespace
        )
        for warning in gh_var_warnings:
            append_audit(pipeline_state, "deploy", "github_variables", "warning", warning)

        ok_commit, commit_output = auto_commit_generated_artifacts(
            repo_path,
            generated,
            "chore(orchestrator): add generated pipeline assets",
        )
        append_audit(pipeline_state, "deploy", "auto_commit", "ok" if ok_commit else "failed", commit_output)
        if not ok_commit:
            pipeline_state.escalate_reason = "auto-commit failed"
            return state
        pipeline_state.commit_sha = commit_output.strip().splitlines()[-1] if commit_output.strip() else "committed"

        if pipeline_state.auto_draft_pr:
            branch_name = f"orchestrator/{pipeline_state.app_name}-pipeline-assets"
            ok_pr, pr_output = create_draft_pr_for_generated_artifacts(
                repo_path=repo_path,
                branch_name=branch_name,
                title=f"chore: add pipeline assets for {pipeline_state.app_name}",
                body=(
                    "Automated draft PR generated by pipeline orchestrator.\n\n"
                    "Includes generated pipeline assets:\n"
                    "- Dockerfile\n"
                    "- CI workflows\n"
                    "- Helm chart manifests\n"
                    "- ArgoCD application\n"
                ),
            )
            append_audit(pipeline_state, "deploy", "auto_draft_pr", "ok" if ok_pr else "failed", pr_output)
            if not ok_pr:
                pipeline_state.escalate_reason = "draft PR creation failed"
                return state
            pipeline_state.pr_url = pr_output

    pipeline_state.clear_pause()
    return state


def _route_after_step(state: OrchestratorGraphState, step: StepName, next_step: Literal["dockerize", "build", "test", "scan", "approve_infra", "provision", "approve_deploy", "deploy", "healthcheck", "finalize"]) -> str:
    pipeline_state = state["pipeline_state"]
    if pipeline_state.escalate_reason:
        return END
    if pipeline_state.step_status[step] == "escalated":
        return END
    return next_step


def _route_after_approve_infra(state: OrchestratorGraphState) -> str:
    pipeline_state = state["pipeline_state"]
    if pipeline_state.paused_for == "approve_infra":
        return END
    return "provision"


def _route_after_approve_deploy(state: OrchestratorGraphState) -> str:
    pipeline_state = state["pipeline_state"]
    if pipeline_state.paused_for == "approve_deploy":
        return END
    return "deploy"


def _route_after_provision(state: OrchestratorGraphState) -> str:
    pipeline_state = state["pipeline_state"]
    if pipeline_state.step_status["provision"] != "ok":
        return END
    if state["phase"] == "bootstrap":
        return "finalize"
    return "approve_deploy"


def _route_after_deploy(state: OrchestratorGraphState) -> str:
    pipeline_state = state["pipeline_state"]
    if pipeline_state.step_status["deploy"] != "ok":
        return END
    return "healthcheck"


def _route_after_healthcheck(state: OrchestratorGraphState) -> str:
    pipeline_state = state["pipeline_state"]
    if pipeline_state.step_status["healthcheck"] != "ok":
        return END
    return "finalize"


def _route_start(state: OrchestratorGraphState) -> str:
    if state["phase"] == "activate":
        return "approve_deploy"
    return "plan"


def approve_infra_gate(state: PipelineState, auto_approve: bool) -> bool:
    if state.approvals.infra:
        state.clear_pause()
        return True
    if auto_approve:
        state.approvals.infra = True
        state.clear_pause()
        append_audit(state, "approve_infra", "approval", "approved", "auto approved")
        return True

    state.pause("approve_infra", state.infra_plan or "")
    append_audit(state, "approve_infra", "approval", "paused", "waiting for human approval")
    return False


def approve_deploy_gate(state: PipelineState, auto_approve: bool) -> bool:
    if state.approvals.deploy:
        state.clear_pause()
        return True
    if auto_approve:
        state.approvals.deploy = True
        state.clear_pause()
        append_audit(state, "approve_deploy", "approval", "approved", "auto approved")
        return True

    state.pause("approve_deploy", state.image_ref or "")
    append_audit(state, "approve_deploy", "approval", "paused", "waiting for human approval")
    return False


def _step_with_retries(
    state: PipelineState,
    step: StepName,
    run_step: Callable[[], tuple[bool, str]],
    repo_path: Path,
) -> bool:
    last_output = ""
    while True:
        ok, output = run_step()
        last_output = output
        append_audit(state, step, "run", "ok" if ok else "failed", output)
        if ok:
            state.mark_step(step, "ok")
            return True

        state.mark_step(step, "failed")
        state.add_retry(step)
        proposal = apply_fix_for_failure(repo_path, step, output, state)
        state.last_fix_proposal = proposal
        append_audit(
            state,
            "diagnose_fix",
            "propose_fix",
            "ok" if not proposal.escalated else "escalated",
            f"fix_type={proposal.fix_type} | {proposal.change_summary}",
        )

        if proposal.escalated or state.retries.get(step, 0) > state.retry_limit:
            state.mark_step(step, "escalated")
            if proposal.root_cause == "Unknown deterministic failure" and last_output.strip():
                state.escalate_reason = f"{step} failed: {last_output.splitlines()[0][:240]}"
            else:
                state.escalate_reason = proposal.root_cause
            return False


def run_pipeline(
    state: PipelineState,
    auto_approve: bool | None = None,
    phase: Literal["full", "bootstrap", "activate"] = "full",
) -> PipelineState:
    auto_approve = auto_approve if auto_approve is not None else os.getenv("AUTO_APPROVE", "0") == "1"
    if phase != "activate" and state.paused_for == "approve_infra" and not state.approvals.infra:
        return state
    if state.paused_for == "approve_deploy" and not state.approvals.deploy:
        return state

    if phase == "activate":
        state.paused_for = None
        state.pending_approval_summary = None
        state.step_status["approve_deploy"] = "pending"
        state.step_status["deploy"] = "pending"
        state.step_status["healthcheck"] = "pending"

    compiled_graph = build_graph()
    graph_state: OrchestratorGraphState = {
        "pipeline_state": state,
        "auto_approve": auto_approve,
        "phase": phase,
    }
    result = compiled_graph.invoke(graph_state)
    return result["pipeline_state"]


def build_graph():
    graph = StateGraph(OrchestratorGraphState)

    graph.add_node("plan", _node_plan)
    graph.add_node("dockerize", _node_dockerize)
    graph.add_node("build", _node_build)
    graph.add_node("test", _node_test)
    graph.add_node("scan", _node_scan)
    graph.add_node("approve_infra", _node_approve_infra)
    graph.add_node("provision", _node_provision)
    graph.add_node("approve_deploy", _node_approve_deploy)
    graph.add_node("deploy", _node_deploy)
    graph.add_node("healthcheck", _node_healthcheck)
    graph.add_node("finalize", _node_finalize)

    graph.add_conditional_edges(START, _route_start, ["plan", "approve_deploy"])
    graph.add_conditional_edges("plan", lambda s: _route_after_step(s, "plan", "dockerize"), ["dockerize", END])
    graph.add_conditional_edges("dockerize", lambda s: _route_after_step(s, "dockerize", "build"), ["build", END])
    graph.add_conditional_edges("build", lambda s: _route_after_step(s, "build", "test"), ["test", END])
    graph.add_conditional_edges("test", lambda s: _route_after_step(s, "test", "scan"), ["scan", END])
    graph.add_conditional_edges("scan", lambda s: _route_after_step(s, "scan", "approve_infra"), ["approve_infra", END])
    graph.add_conditional_edges("approve_infra", _route_after_approve_infra, ["provision", END])
    graph.add_conditional_edges("provision", _route_after_provision, ["approve_deploy", "finalize", END])
    graph.add_conditional_edges("approve_deploy", _route_after_approve_deploy, ["deploy", END])
    graph.add_conditional_edges("deploy", _route_after_deploy, ["healthcheck", END])
    graph.add_conditional_edges("healthcheck", _route_after_healthcheck, ["finalize", END])
    graph.add_edge("finalize", END)

    return graph.compile()
