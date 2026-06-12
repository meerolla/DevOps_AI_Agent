from __future__ import annotations

import re
from pathlib import Path

from orchestrator.state import AuditEntry, PipelineState

SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"(?i)(api[_-]?key|token|password)\s*[:=]\s*[^\s]+"),
    re.compile(r"(?i)authorization:\s*bearer\s+[^\s]+"),
]


def sanitize_log_text(text: str) -> str:
    sanitized = text
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def append_audit(state: PipelineState, step: str, action: str, status: str, details: str = "") -> None:
    state.audit.append(
        AuditEntry(
            step=step,
            action=action,
            status=status,
            details=sanitize_log_text(details),
        )
    )


def write_audit_log(state: PipelineState, output_path: Path) -> None:
    lines = []
    for entry in state.audit:
        lines.append(
            f"{entry.timestamp} | step={entry.step} | action={entry.action} | "
            f"status={entry.status} | details={entry.details}"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
