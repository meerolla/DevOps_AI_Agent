from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from orchestrator.state import BuildPlan, FixProposal


@dataclass
class LLMConfig:
    mode: str
    provider: str


class MockLLM:
    def plan_repo(self, repo_path: Path) -> BuildPlan:
        language = "python" if (repo_path / "app.py").exists() else "unknown"
        framework = "pytest-app" if (repo_path / "tests").exists() else "unknown"
        entrypoint = "app.py" if (repo_path / "app.py").exists() else "unknown"
        test_cmd = "pytest -q" if (repo_path / "tests").exists() else "unknown"
        notes = []
        if language == "unknown":
            notes.append("language_unknown_needs_human")
        return BuildPlan(
            language=language,
            framework=framework,
            entrypoint=entrypoint,
            ports=[8000],
            dependencies=[],
            stateful=False,
            needs_db=False,
            test_command=test_cmd,
            notes=notes,
        )

    def dockerize(self, plan: BuildPlan) -> str:
        return "\n".join(
            [
                "FROM python:3.12.3-slim AS runtime",
                "WORKDIR /app",
                "RUN useradd -m appuser",
                "COPY . /app",
                "RUN pip install --no-cache-dir pytest==8.2.2",
                "USER appuser",
                "CMD [\"python\", \"-m\", \"http.server\", \"8000\"]",
                "",
            ]
        )

    def diagnose(self, failed_step: str, failure_output: str) -> FixProposal:
        if failed_step == "test" and "Expected 5" in failure_output:
            return FixProposal(
                root_cause="Bug in add implementation in app.py",
                confidence=0.95,
                change_summary="Replace subtraction with addition in app.py",
                retry_step="test",
            )
        return FixProposal(
            root_cause="Unknown deterministic failure",
            confidence=0.2,
            change_summary="Escalate to human",
            retry_step="test",
            escalated=True,
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
        files = sorted(str(p.relative_to(repo_path)) for p in repo_path.rglob("*") if p.is_file())
        prompt = (
            "Inspect this repository file list and infer a BuildPlan. "
            "If a field is unknown, return 'unknown' or null and include a note.\n"
            f"Files:\n" + "\n".join(files[:400])
        )
        payload = self._chat_json(
            system_prompt=(
                "Return strict JSON with keys: language, framework, entrypoint, ports, dependencies, "
                "stateful, needs_db, test_command, notes."
            ),
            user_prompt=prompt,
        )
        try:
            return BuildPlan.model_validate(payload)
        except Exception:
            return super().plan_repo(repo_path)

    def dockerize(self, plan: BuildPlan) -> str:
        prompt = (
            "Create a secure Dockerfile for this plan. Requirements: pinned base image, non-root user, "
            "no secret material, and include only necessary build steps.\n"
            f"Plan: {plan.model_dump_json()}"
        )
        dockerfile = self._chat_text(
            system_prompt="Return only Dockerfile content without markdown fences.",
            user_prompt=prompt,
        )
        return dockerfile or super().dockerize(plan)

    def diagnose(self, failed_step: str, failure_output: str) -> FixProposal:
        prompt = (
            "Diagnose a pipeline failure and propose a safe fix for only the failing step. "
            "Never weaken tests or scans.\n"
            f"Failed step: {failed_step}\n"
            f"Failure output:\n{failure_output[:6000]}"
        )
        payload = self._chat_json(
            system_prompt=(
                "Return strict JSON with keys: root_cause, confidence, change_summary, retry_step, escalated."
            ),
            user_prompt=prompt,
        )
        try:
            payload.setdefault("retry_step", failed_step)
            return FixProposal.model_validate(payload)
        except Exception:
            return super().diagnose(failed_step, failure_output)


def get_llm() -> MockLLM:
    mode = os.getenv("LLM_MODE", "mock").lower()
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    config = LLMConfig(mode=mode, provider=provider)
    if config.mode == "mock":
        return MockLLM()
    return ProviderLLM()
