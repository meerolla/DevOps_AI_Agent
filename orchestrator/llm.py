from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.state import BuildPlan, FixProposal


def _extract_first_port(text: str) -> int | None:
    for pattern in (r"--port\s+(\d+)", r"port\s*=\s*(\d+)", r"listen\((\d+)\)"):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _normalize_build_plan_payload(payload: dict[str, Any]) -> BuildPlan:
    normalized = dict(payload)
    if "port" in normalized and "ports" not in normalized:
        port_value = normalized.get("port")
        try:
            normalized["ports"] = [int(port_value)] if port_value is not None else []
        except (TypeError, ValueError):
            normalized["ports"] = []
    if "ports" in normalized and isinstance(normalized["ports"], int):
        normalized["ports"] = [normalized["ports"]]
    normalized.setdefault("dependencies", [])
    normalized.setdefault("notes", [])
    normalized.setdefault("stateful", False)
    normalized.setdefault("needs_db", False)
    return BuildPlan.model_validate(normalized)


def _detect_test_command(files: list[str], dependencies: dict[str, str]) -> str:
    package_json = dependencies.get("package.json", "")
    if package_json:
        if '"test"' in package_json and "jest" in package_json.lower():
            return "npm test"
        if '"test"' in package_json:
            return "npm run test"
    if any(path.startswith("tests/") for path in files):
        return "pytest -q"
    if "pom.xml" in dependencies:
        return "mvn test"
    if "go.mod" in dependencies:
        return "go test ./..."
    return "unknown"


def _detect_language_framework(files: list[str], dependencies: dict[str, str]) -> tuple[str, str]:
    req = dependencies.get("requirements.txt", "").lower()
    pkg = dependencies.get("package.json", "").lower()
    if "fastapi" in req:
        return "python", "fastapi"
    if "flask" in req:
        return "python", "flask"
    if "django" in req:
        return "python", "django"
    if "express" in pkg:
        return "node", "express"
    if "spring-boot" in dependencies.get("pom.xml", "").lower():
        return "java", "springboot"
    if "go.mod" in dependencies:
        return "go", "go"
    if any(path.endswith(".py") for path in files):
        return "python", "unknown"
    if any(path.endswith(".js") for path in files):
        return "node", "unknown"
    return "unknown", "unknown"


def _detect_entrypoint(files: list[str], framework: str) -> str:
    preferred = [
        "app/main.py",
        "main.py",
        "app.py",
        "src/index.js",
        "index.js",
    ]
    for candidate in preferred:
        if candidate in files:
            if framework == "fastapi" and candidate == "app/main.py":
                return "app.main:app"
            return candidate
    return "unknown"


def _default_dockerfile_for_plan(plan: BuildPlan, dependency_files: list[str]) -> str:
    port = plan.ports[0] if plan.ports else 8000
    framework = (plan.framework or "").lower()
    language = (plan.language or "").lower()

    if framework == "fastapi":
        install_line = "RUN pip install --no-cache-dir -r requirements.txt" if "requirements.txt" in dependency_files else "RUN pip install --no-cache-dir fastapi uvicorn"
        return "\n".join(
            [
                "FROM python:3.12-slim AS runtime",
                "WORKDIR /app",
                "RUN useradd -m appuser",
                "COPY requirements.txt /app/requirements.txt",
                install_line,
                "COPY . /app",
                "USER appuser",
                f'CMD ["uvicorn", "{plan.entrypoint if plan.entrypoint != "unknown" else "app.main:app"}", "--host", "0.0.0.0", "--port", "{port}"]',
                "",
            ]
        )

    if framework == "express" or language == "node":
        entrypoint = plan.entrypoint if plan.entrypoint != "unknown" else "src/index.js"
        return "\n".join(
            [
                "FROM node:20-slim AS runtime",
                "WORKDIR /app",
                "COPY package*.json /app/",
                "RUN npm ci --omit=dev || npm install --omit=dev",
                "COPY . /app",
                "EXPOSE 3000",
                f'CMD ["node", "{entrypoint}"]',
                "",
            ]
        )

    if language == "python":
        entrypoint = plan.entrypoint if plan.entrypoint.endswith(".py") else "app.py"
        install_line = "RUN pip install --no-cache-dir -r requirements.txt" if "requirements.txt" in dependency_files else "RUN pip install --no-cache-dir pytest==8.2.2"
        return "\n".join(
            [
                "FROM python:3.12-slim AS runtime",
                "WORKDIR /app",
                "RUN useradd -m appuser",
                "COPY . /app",
                install_line,
                "USER appuser",
                f'CMD ["python", "{entrypoint}"]',
                "",
            ]
        )

    return "\n".join(
        [
            "FROM alpine:3.20",
            "WORKDIR /app",
            "COPY . /app",
            "CMD [\"sh\", \"-c\", \"echo 'unknown app type'; sleep 3600\"]",
            "",
        ]
    )


@dataclass
class LLMConfig:
    mode: str
    provider: str


class MockLLM:
    def plan_from_evidence(self, evidence: dict[str, Any]) -> BuildPlan:
        files = evidence.get("files", []) or []
        dependencies = evidence.get("dependencies", {}) or {}
        entrypoint_files = evidence.get("entrypoint_files", {}) or {}

        language, framework = _detect_language_framework(files, dependencies)
        entrypoint = _detect_entrypoint(files, framework)
        ports: list[int] = []
        for content in list(entrypoint_files.values()) + list(dependencies.values()):
            port = _extract_first_port(content)
            if port:
                ports.append(port)
                break
        if not ports:
            ports = [3000] if framework == "express" else [8000]

        deps = sorted({
            dep
            for content in dependencies.values()
            for dep in re.findall(r"[A-Za-z0-9_.-]+", content)
            if dep and not dep.isdigit()
        })[:20]

        notes: list[str] = []
        if framework == "unknown":
            notes.append("framework_inferred_with_low_confidence")

        return BuildPlan(
            language=language,
            framework=framework,
            entrypoint=entrypoint,
            ports=ports,
            dependencies=deps,
            stateful=False,
            needs_db=False,
            test_command=_detect_test_command(files, dependencies),
            notes=notes,
        )

    def plan_repo(self, repo_path: Path) -> BuildPlan:
        files = sorted(str(p.relative_to(repo_path)).replace("\\", "/") for p in repo_path.rglob("*") if p.is_file())
        dependency_files = [
            "requirements.txt",
            "package.json",
            "pom.xml",
            "build.gradle",
            "go.mod",
            "Gemfile",
        ]
        dependencies: dict[str, str] = {}
        for dep in dependency_files:
            path = repo_path / dep
            if path.exists():
                dependencies[dep] = path.read_text(encoding="utf-8", errors="replace")

        entry_candidates = ["app/main.py", "main.py", "app.py", "src/index.js", "index.js"]
        entrypoint_files: dict[str, str] = {}
        for candidate in entry_candidates:
            path = repo_path / candidate
            if path.exists():
                entrypoint_files[candidate] = path.read_text(encoding="utf-8", errors="replace")

        return self.plan_from_evidence(
            {
                "files": files,
                "dependencies": dependencies,
                "entrypoint_files": entrypoint_files,
            }
        )

    def dockerize_from_evidence(
        self,
        plan: BuildPlan,
        evidence: dict[str, Any],
        build_error: str | None = None,
    ) -> str:
        dependency_files = evidence.get("dependency_files", []) or []
        _ = build_error  # deterministic mock currently ignores build output for regeneration
        return _default_dockerfile_for_plan(plan, dependency_files)

    def dockerize(self, plan: BuildPlan) -> str:
        return self.dockerize_from_evidence(plan, {"dependency_files": ["requirements.txt"]})

    def diagnose(self, failed_step: str, failure_output: str) -> FixProposal:
        retry_step = failed_step if failed_step in {"build", "test", "scan", "provision", "deploy", "healthcheck"} else "build"
        fix_type = "escalate"
        hint = "Review the audit log for details and address the root cause manually."
        root = "Unknown failure — escalating to human"
        if "permission denied" in failure_output.lower() or "unauthorized" in failure_output.lower():
            fix_type = "infra_hint"
            hint = "Verify Docker/cluster/registry credentials and permissions."
            root = "Infrastructure permission issue"
        return FixProposal(
            root_cause=root,
            confidence=0.35,
            change_summary="Escalate to human",
            retry_step=retry_step,  # type: ignore[arg-type]
            escalated=True,
            fix_type=fix_type,
            hint=hint,
        )


class ProviderLLM(MockLLM):
    """Provider-backed LLM implementation used when LLM_MODE is not mock."""

    def __init__(self) -> None:
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._client = self._build_client()

    def _build_client(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_MODE is not mock")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required for provider mode") from exc

        return OpenAI(api_key=api_key)

    def _chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    def _chat_text(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return (response.choices[0].message.content or "").strip()

    def plan_repo(self, repo_path: Path) -> BuildPlan:
        files = sorted(str(p.relative_to(repo_path)).replace("\\", "/") for p in repo_path.rglob("*") if p.is_file())
        dependency_files = [
            "requirements.txt",
            "package.json",
            "pom.xml",
            "build.gradle",
            "go.mod",
            "Gemfile",
            "pipeline-setup.yaml",
        ]
        dependencies: dict[str, str] = {}
        for dep in dependency_files:
            path = repo_path / dep
            if path.exists():
                dependencies[dep] = path.read_text(encoding="utf-8", errors="replace")

        entry_candidates = ["app/main.py", "main.py", "app.py", "src/index.js", "index.js"]
        entrypoint_files: dict[str, str] = {}
        for candidate in entry_candidates:
            path = repo_path / candidate
            if path.exists():
                entrypoint_files[candidate] = path.read_text(encoding="utf-8", errors="replace")

        return self.plan_from_evidence(
            {
                "files": files,
                "dependencies": dependencies,
                "entrypoint_files": entrypoint_files,
            }
        )

    def plan_from_evidence(self, evidence: dict[str, Any]) -> BuildPlan:
        files = evidence.get("files", []) or []
        dependencies = evidence.get("dependencies", {}) or {}
        entrypoint_files = evidence.get("entrypoint_files", {}) or {}

        prompt = (
            "Inspect this repository evidence and infer a BuildPlan. "
            "If a field is unknown, return 'unknown' or null and include a note.\n\n"
            "Return strict JSON with keys: language, framework, entrypoint, ports, dependencies, "
            "stateful, needs_db, test_command, notes.\n\n"
            f"Files:\n{json.dumps(files[:500], indent=2)}\n\n"
            f"Dependency files:\n{json.dumps(dependencies, indent=2)[:12000]}\n\n"
            f"Entrypoint candidates:\n{json.dumps(entrypoint_files, indent=2)[:12000]}"
        )
        payload = self._chat_json(
            system_prompt="You are the Planner agent. Produce an evidence-based BuildPlan.",
            user_prompt=prompt,
        )
        try:
            return _normalize_build_plan_payload(payload)
        except Exception:
            return super().plan_from_evidence(evidence)

    def dockerize(self, plan: BuildPlan) -> str:
        return self.dockerize_from_evidence(plan, {"dependency_files": ["requirements.txt"]})

    def dockerize_from_evidence(
        self,
        plan: BuildPlan,
        evidence: dict[str, Any],
        build_error: str | None = None,
    ) -> str:
        prompt = (
            "Create a secure Dockerfile for this app plan. Requirements: pinned base image, non-root user, "
            "no secret material, and include only necessary build steps.\n"
            "Read evidence and pick framework-specific runtime commands.\n"
            f"Plan: {plan.model_dump_json()}\n"
            f"Evidence: {json.dumps(evidence, indent=2)[:14000]}\n"
        )
        if build_error:
            prompt += f"Previous build error:\n{build_error[:6000]}\nRegenerate Dockerfile to address this."
        dockerfile = self._chat_text(
            system_prompt="Return only Dockerfile content without markdown fences.",
            user_prompt=prompt,
        )
        return dockerfile or _default_dockerfile_for_plan(plan, evidence.get("dependency_files", []))

    def diagnose(self, failed_step: str, failure_output: str) -> FixProposal:
        return self.diagnose_with_context(failed_step, failure_output, {})

    def diagnose_with_context(
        self,
        failed_step: str,
        failure_output: str,
        context_files: dict[str, str],
    ) -> FixProposal:
        prompt = (
            "Diagnose a pipeline failure in a CI/CD orchestrator. "
            "Never weaken tests or scans. Do not propose changes to application source code.\n"
            f"Failed step: {failed_step}\n"
            f"Failure output:\n{failure_output[:6000]}\n"
            f"Context files:\n{json.dumps(context_files, indent=2)[:12000]}"
        )
        payload = self._chat_json(
            system_prompt=(
                "Return strict JSON with keys: root_cause, confidence, change_summary, "
                "retry_step, escalated, fix_type, hint. "
                "fix_type must be one of: infra_hint, config_hint, tool_retry, escalate. "
                "hint must be a short actionable string for the operator."
            ),
            user_prompt=prompt,
        )
        try:
            payload.setdefault("retry_step", failed_step)
            payload.setdefault("fix_type", "escalate")
            payload.setdefault("hint", "")
            return FixProposal.model_validate(payload)
        except Exception:
            return super().diagnose(failed_step, failure_output)


def _to_step_name(candidate: str) -> str:
    valid = {"build", "test", "scan", "provision", "deploy", "healthcheck"}
    return candidate if candidate in valid else "build"


def get_llm() -> MockLLM:
    mode = os.getenv("LLM_MODE", "mock").lower()
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    config = LLMConfig(mode=mode, provider=provider)
    if config.mode == "mock":
        return MockLLM()
    return ProviderLLM()
