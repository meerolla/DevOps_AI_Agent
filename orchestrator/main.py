from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orchestrator.audit import write_audit_log
from orchestrator.graph import run_pipeline
from orchestrator.state import PipelineState


def _state_file(repo: str) -> Path:
    return Path(repo) / ".orchestrator_state.json"


def _load_state(repo: str) -> PipelineState:
    state_file = _state_file(repo)
    return PipelineState.model_validate_json(state_file.read_text(encoding="utf-8"))


def _save_state(state: PipelineState) -> Path:
    state_file = _state_file(state.repo_ref)
    state.state_file_ref = str(state_file)
    state_file.write_text(json.dumps(state.model_dump(), indent=2), encoding="utf-8")
    return state_file


def _render_pause_instruction(state: PipelineState) -> str:
    if state.paused_for == "approve_infra":
        return (
            "Pipeline paused for infrastructure approval.\n"
            f"Plan:\n{state.pending_approval_summary or ''}\n"
            f"Run: python -m orchestrator.main approve --repo {state.repo_ref} --step infra\n"
            f"Then: python -m orchestrator.main resume --repo {state.repo_ref}"
        )
    return (
        "Pipeline paused for deploy approval.\n"
        f"Image:\n{state.pending_approval_summary or ''}\n"
        f"Run: python -m orchestrator.main approve --repo {state.repo_ref} --step deploy\n"
        f"Then: python -m orchestrator.main resume --repo {state.repo_ref}"
    )


def _render_failure_summary(state: PipelineState) -> str:
    failed_steps = [step for step, outcome in state.step_status.items() if outcome in {"failed", "escalated"}]
    lines = []
    if failed_steps:
        lines.append(f"Failed steps: {', '.join(failed_steps)}")
    elif state.paused_for:
        lines.append(f"Pipeline paused for approval: {state.paused_for}")
    else:
        lines.append("No explicit failed step captured")
    if state.last_fix_proposal:
        p = state.last_fix_proposal
        lines.append(f"Diagnosis [{p.fix_type}]: {p.root_cause}")
        if p.hint:
            lines.append(f"Suggested action: {p.hint}")
    return "\n".join(lines)


def run_command(
    repo: str,
    goal: str,
    cluster: str,
    registry: str,
    namespace: str,
    auto_approve: bool,
    auto_commit: bool,
    auto_draft_pr: bool,
) -> int:
    state = PipelineState(
        goal=goal,
        repo_ref=repo,
        cluster=cluster,
        registry=registry,
        namespace=namespace,
        app_name=Path(registry.split(":")[0]).name,
        auto_commit=auto_commit,
        auto_draft_pr=auto_draft_pr,
    )
    final_state = run_pipeline(state, auto_approve=auto_approve, phase="bootstrap")

    audit_path = Path(repo) / ".orchestrator_audit.log"
    write_audit_log(final_state, audit_path)
    state_path = _save_state(final_state)

    if final_state.paused_for:
        print(_render_pause_instruction(final_state))
        print(f"State file: {state_path}")
        print(f"Audit log: {audit_path}")
        return 2

    bootstrap_required_steps = [
        "plan",
        "dockerize",
        "build",
        "test",
        "scan",
        "approve_infra",
        "provision",
    ]
    all_ok = all(final_state.step_status[step] == "ok" for step in bootstrap_required_steps)
    if all_ok:
        print("Pipeline completed successfully.")
        if final_state.commit_sha:
            print(f"Auto-commit result: {final_state.commit_sha}")
        if final_state.pr_url:
            print(f"Draft PR: {final_state.pr_url}")
        print(f"Audit log: {audit_path}")
        return 0

    print("Pipeline did not fully complete.")
    print(f"Escalation: {final_state.escalate_reason or 'approval not granted or step failure'}")
    print(_render_failure_summary(final_state))
    print(f"Audit log: {audit_path}")
    return 1


def activate_command(
    repo: str,
    cluster: str,
    registry: str,
    namespace: str,
    auto_approve_deploy: bool,
) -> int:
    state = PipelineState(
        goal="post-merge gitops activation",
        repo_ref=repo,
        cluster=cluster,
        registry=registry,
        namespace=namespace,
        app_name=Path(registry.split(":")[0]).name,
        auto_commit=False,
        auto_draft_pr=False,
    )
    if auto_approve_deploy:
        state.approvals.deploy = True

    final_state = run_pipeline(state, auto_approve=auto_approve_deploy, phase="activate")
    audit_path = Path(repo) / ".orchestrator_audit.log"
    write_audit_log(final_state, audit_path)
    _save_state(final_state)

    if final_state.paused_for:
        print(_render_pause_instruction(final_state))
        return 2

    all_ok = all(final_state.step_status[step] == "ok" for step in ["approve_deploy", "deploy", "healthcheck"])
    if all_ok:
        print("Post-merge activation completed successfully.")
        print(f"Audit log: {audit_path}")
        return 0

    print("Post-merge activation did not fully complete.")
    print(f"Escalation: {final_state.escalate_reason or 'deploy or healthcheck failed'}")
    print(_render_failure_summary(final_state))
    print(f"Audit log: {audit_path}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline setup orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run the orchestration pipeline")
    run_parser.add_argument("--repo", required=True, help="Repository path")
    run_parser.add_argument("--cluster", required=True, help="Kubernetes context name")
    run_parser.add_argument("--registry", required=True, help="Container registry reference, e.g. ghcr.io/org/app")
    run_parser.add_argument("--namespace", required=True, help="Target Kubernetes namespace")
    run_parser.add_argument("--goal", default="given an app repo, set up CI/CD and deploy it", help="Goal description")
    run_parser.add_argument("--auto-approve", action="store_true", help="Auto approve both gates")
    run_parser.add_argument("--no-auto-commit", action="store_true", help="Disable auto-commit of generated artifacts")
    run_parser.add_argument("--no-draft-pr", action="store_true", help="Disable automatic draft PR creation")

    activate_parser = sub.add_parser("activate", help="Run post-merge deploy activation workflow")
    activate_parser.add_argument("--repo", required=True, help="Repository path")
    activate_parser.add_argument("--cluster", required=True, help="Kubernetes context name")
    activate_parser.add_argument("--registry", required=True, help="Container registry reference, e.g. ghcr.io/org/app")
    activate_parser.add_argument("--namespace", required=True, help="Target Kubernetes namespace")
    activate_parser.add_argument(
        "--auto-approve-deploy",
        action="store_true",
        help="Automatically approve deploy gate for non-interactive workflow runs",
    )

    approve_parser = sub.add_parser("approve", help="Approve a paused gate")
    approve_parser.add_argument("--repo", required=True, help="Repository path")
    approve_parser.add_argument("--step", choices=["infra", "deploy"], required=True, help="Gate to approve")

    resume_parser = sub.add_parser("resume", help="Resume from a paused run")
    resume_parser.add_argument("--repo", required=True, help="Repository path")
    resume_parser.add_argument("--auto-approve", action="store_true", help="Auto approve remaining gates")

    retry_parser = sub.add_parser("retry", help="Retry pipeline from a specific step after manual fix")
    retry_parser.add_argument("--repo", required=True, help="Repository path")
    retry_parser.add_argument(
        "--from-step",
        required=True,
        choices=["test", "scan", "approve_infra", "provision", "approve_deploy", "deploy", "healthcheck"],
        help="Step to resume from (resets this step and all subsequent steps)",
    )
    retry_parser.add_argument("--auto-approve", action="store_true", help="Auto approve remaining gates")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        return run_command(
            repo=args.repo,
            goal=args.goal,
            cluster=args.cluster,
            registry=args.registry,
            namespace=args.namespace,
            auto_approve=args.auto_approve,
            auto_commit=not args.no_auto_commit,
            auto_draft_pr=not args.no_draft_pr,
        )

    if args.command == "approve":
        state = _load_state(args.repo)
        if args.step == "infra":
            state.approvals.infra = True
        if args.step == "deploy":
            state.approvals.deploy = True
        _save_state(state)
        print(f"Approved: {args.step}")
        return 0

    if args.command == "activate":
        return activate_command(
            repo=args.repo,
            cluster=args.cluster,
            registry=args.registry,
            namespace=args.namespace,
            auto_approve_deploy=args.auto_approve_deploy,
        )

    if args.command == "resume":
        state = _load_state(args.repo)
        final_state = run_pipeline(state, auto_approve=args.auto_approve, phase="bootstrap")

        audit_path = Path(args.repo) / ".orchestrator_audit.log"
        write_audit_log(final_state, audit_path)
        _save_state(final_state)

        if final_state.paused_for:
            print(_render_pause_instruction(final_state))
            return 2

        bootstrap_required_steps = [
            "plan",
            "dockerize",
            "build",
            "test",
            "scan",
            "approve_infra",
            "provision",
        ]
        all_ok = all(final_state.step_status[step] == "ok" for step in bootstrap_required_steps)
        if all_ok:
            print("Pipeline completed successfully.")
            return 0

        print("Pipeline did not fully complete.")
        print(f"Escalation: {final_state.escalate_reason or 'approval not granted or step failure'}")
        print(_render_failure_summary(final_state))
        return 1

    if args.command == "retry":
        state = _load_state(args.repo)
        state.retry_from_step(args.from_step)  # type: ignore[arg-type]
        _save_state(state)
        print(f"State reset from step '{args.from_step}'. Resuming pipeline...")
        final_state = run_pipeline(state, auto_approve=args.auto_approve)

        audit_path = Path(args.repo) / ".orchestrator_audit.log"
        write_audit_log(final_state, audit_path)
        _save_state(final_state)

        if final_state.paused_for:
            print(_render_pause_instruction(final_state))
            return 2

        all_ok = all(status == "ok" for status in final_state.step_status.values())
        if all_ok:
            print("Pipeline completed successfully.")
            return 0

        print("Pipeline did not fully complete.")
        print(f"Escalation: {final_state.escalate_reason or 'step failure'}")
        print(_render_failure_summary(final_state))
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
