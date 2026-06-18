from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

StepName = Literal[
    "plan",
    "dockerize",
    "build",
    "test",
    "scan",
    "approve_infra",
    "provision",
    "approve_deploy",
    "deploy",
    "healthcheck",
]
StepOutcome = Literal["pending", "ok", "failed", "escalated"]
PauseReason = Literal["approve_infra", "approve_deploy"]
FixType = Literal["infra_hint", "config_hint", "tool_retry", "escalate"]


class BuildPlan(BaseModel):
    language: str = "unknown"
    framework: str = "unknown"
    entrypoint: str = "unknown"
    ports: List[int] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    stateful: Optional[bool] = None
    needs_db: Optional[bool] = None
    test_command: str = "unknown"
    notes: List[str] = Field(default_factory=list)


class FixProposal(BaseModel):
    root_cause: str
    confidence: float
    change_summary: str
    retry_step: StepName
    escalated: bool = False
    fix_type: FixType = "escalate"
    hint: str = ""  # actionable operator message


class ToolResult(BaseModel):
    ok: bool
    step: StepName
    details: str = ""
    output: str = ""
    artifact_ref: Optional[str] = None
    test_artifact_ref: Optional[str] = None


class AuditEntry(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    step: str
    action: str
    status: str
    details: str = ""


class PipelineApprovals(BaseModel):
    infra: bool = False
    deploy: bool = False


class PipelineState(BaseModel):
    goal: str
    repo_ref: str
    cluster: str = "default"
    registry: str = "ghcr.io/demo/sample"
    namespace: str = "demo"
    app_name: str = "app"
    pull_secret_name: str = "ghcr-pull-secret"
    auto_commit: bool = True
    auto_draft_pr: bool = True
    require_tests: bool = False
    build_plan: Optional[BuildPlan] = None
    dockerfile_ref: Optional[str] = None
    image_ref: Optional[str] = None
    test_image_ref: Optional[str] = None
    test_results: Optional[str] = None
    scan_report: Optional[str] = None
    manifests_ref: Optional[str] = None
    infra_plan: Optional[str] = None
    infra_plan_generated: bool = False
    approvals: PipelineApprovals = Field(default_factory=PipelineApprovals)
    step_status: Dict[StepName, StepOutcome] = Field(
        default_factory=lambda: {
            "plan": "pending",
            "dockerize": "pending",
            "build": "pending",
            "test": "pending",
            "scan": "pending",
            "approve_infra": "pending",
            "provision": "pending",
            "approve_deploy": "pending",
            "deploy": "pending",
            "healthcheck": "pending",
        }
    )
    audit: List[AuditEntry] = Field(default_factory=list)
    retries: Dict[StepName, int] = Field(default_factory=dict)
    retry_limit: int = 2
    last_failed_step: Optional[StepName] = None
    escalate_reason: Optional[str] = None
    last_fix_proposal: Optional[FixProposal] = None
    paused_for: Optional[PauseReason] = None
    pending_approval_summary: Optional[str] = None
    state_file_ref: Optional[str] = None
    commit_sha: Optional[str] = None
    pr_url: Optional[str] = None

    def mark_step(self, step: StepName, outcome: StepOutcome) -> None:
        self.step_status[step] = outcome
        if outcome in {"failed", "escalated"}:
            self.last_failed_step = step

    def add_retry(self, step: StepName) -> int:
        current = self.retries.get(step, 0) + 1
        self.retries[step] = current
        return current

    def image_ref_for_registry(self) -> str:
        return f"{self.registry}:latest"

    def pause(self, reason: PauseReason, summary: str) -> None:
        self.paused_for = reason
        self.pending_approval_summary = summary

    def clear_pause(self) -> None:
        self.paused_for = None
        self.pending_approval_summary = None

    def retry_from_step(self, from_step: StepName) -> None:
        """Reset escalation state and mark all steps from from_step onward as pending.

        Preserves completed earlier steps (plan, dockerize, build, etc.) so the
        pipeline resumes mid-flow without re-running expensive steps.
        """
        _ORDER: list[StepName] = [
            "plan", "dockerize", "build", "test", "scan",
            "approve_infra", "provision", "approve_deploy", "deploy", "healthcheck",
        ]
        reset_from = _ORDER.index(from_step)
        for step in _ORDER[reset_from:]:
            self.step_status[step] = "pending"
            self.retries.pop(step, None)
        self.escalate_reason = None
        self.last_fix_proposal = None
        self.last_failed_step = None
