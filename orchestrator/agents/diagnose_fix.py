from __future__ import annotations

from pathlib import Path

from orchestrator.llm import get_llm
from orchestrator.state import FixProposal, StepName

BLOCKED_PATTERNS = (
    "@pytest.mark.skip",
    "pytest.skip(",
    "xfail",
    "assert True",
    "--severity CRITICAL",
    "--exit-code 0",
)


def is_test_scan_weakening_change(change_text: str) -> bool:
    lowered = change_text.lower()
    return any(pattern.lower() in lowered for pattern in BLOCKED_PATTERNS)


def apply_fix_for_failure(
    repo_path: Path,
    failed_step: StepName,
    failure_output: str,
) -> FixProposal:
    llm = get_llm()
    proposal = llm.diagnose(failed_step, failure_output)

    if proposal.escalated:
        return proposal

    if failed_step in {"test", "scan"} and is_test_scan_weakening_change(proposal.change_summary):
        return FixProposal(
            root_cause="Proposed change weakens test/scan safeguards",
            confidence=1.0,
            change_summary="Rejected unsafe fix proposal",
            retry_step=failed_step,
            escalated=True,
        )

    if failed_step == "test" and "addition" in proposal.change_summary.lower():
        app_file = repo_path / "app.py"
        code = app_file.read_text(encoding="utf-8")
        code = code.replace("return a - b", "return a + b")
        app_file.write_text(code, encoding="utf-8")

    return proposal
