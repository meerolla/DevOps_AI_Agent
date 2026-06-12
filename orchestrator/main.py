from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestrator.audit import write_audit_log
from orchestrator.graph import run_pipeline
from orchestrator.state import PipelineState


def run_command(repo: str, goal: str, auto_approve: bool) -> int:
    state = PipelineState(goal=goal, repo_ref=repo)
    final_state = run_pipeline(state, auto_approve=auto_approve)

    audit_path = Path(repo) / ".orchestrator_audit.log"
    write_audit_log(final_state, audit_path)

    all_ok = all(status == "ok" for status in final_state.step_status.values())
    if all_ok:
        print("Pipeline completed successfully.")
        print(f"Audit log: {audit_path}")
        return 0

    print("Pipeline did not fully complete.")
    print(f"Escalation: {final_state.escalate_reason or 'approval not granted or step failure'}")
    print(f"Audit log: {audit_path}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline setup orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run the orchestration pipeline")
    run_parser.add_argument("--repo", required=True, help="Repository path")
    run_parser.add_argument("--goal", required=True, help="Goal description")
    run_parser.add_argument("--auto-approve", action="store_true", help="Auto approve both gates")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        return run_command(args.repo, args.goal, args.auto_approve)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
