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


class ToolResult(BaseModel):
    ok: bool
    step: StepName
    details: str = ""
    output: str = ""
    artifact_ref: Optional[str] = None


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
    build_plan: Optional[BuildPlan] = None
    dockerfile_ref: Optional[str] = None
    image_ref: Optional[str] = None
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

    def mark_step(self, step: StepName, outcome: StepOutcome) -> None:
        self.step_status[step] = outcome
        if outcome in {"failed", "escalated"}:
            self.last_failed_step = step

    def add_retry(self, step: StepName) -> int:
        current = self.retries.get(step, 0) + 1
        self.retries[step] = current
        return current
