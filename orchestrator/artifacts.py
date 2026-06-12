from __future__ import annotations

from pathlib import Path

from orchestrator.state import BuildPlan, PipelineState


def _workflow_ci() -> str:
    return """name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest -q
"""


def _workflow_self_heal() -> str:
    return """name: ci-self-heal

on:
  workflow_run:
    workflows: [ci]
    types: [completed]

jobs:
  diagnose:
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    runs-on: ubuntu-latest
    steps:
      - name: Placeholder self-heal hook
        run: echo 'Invoke stage-3 self-heal workflow here'
"""


def _helm_chart_yaml(app_name: str) -> str:
    return f"""apiVersion: v2
name: {app_name}
version: 0.1.0
appVersion: \"latest\"
"""


def _helm_values(registry: str, namespace: str) -> str:
    repo, tag = registry.rsplit(":", 1) if ":" in registry else (registry, "latest")
    return f"""image:
  repository: {repo}
  tag: {tag}

namespace: {namespace}

service:
  port: 8000
"""


def _helm_deployment(app_name: str, pull_secret_name: str) -> str:
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app_name}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {app_name}
  template:
    metadata:
      labels:
        app: {app_name}
    spec:
      imagePullSecrets:
      - name: {pull_secret_name}
      containers:
      - name: {app_name}
        image: \"{{{{ .Values.image.repository }}}}:{{{{ .Values.image.tag }}}}\"
        ports:
        - containerPort: 8000
---
apiVersion: v1
kind: Service
metadata:
  name: {app_name}
spec:
  selector:
    app: {app_name}
  ports:
  - port: 8000
    targetPort: 8000
"""


def _argocd_application(app_name: str, namespace: str) -> str:
    return f"""apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {app_name}
  namespace: argocd
spec:
  project: default
  source:
    repoURL: file://.
    targetRevision: HEAD
    path: helm
  destination:
    server: https://kubernetes.default.svc
    namespace: {namespace}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
"""


def generate_pipeline_artifacts(state: PipelineState, plan: BuildPlan) -> list[Path]:
    repo = Path(state.repo_ref)
    app_name = state.app_name

    workflow_dir = repo / ".github" / "workflows"
    helm_templates = repo / "helm" / "templates"
    argocd_dir = repo / "argocd"

    workflow_dir.mkdir(parents=True, exist_ok=True)
    helm_templates.mkdir(parents=True, exist_ok=True)
    argocd_dir.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []

    dockerfile_path = repo / "Dockerfile"
    if not dockerfile_path.exists():
        dockerfile_path.write_text(
            "\n".join(
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
            ),
            encoding="utf-8",
        )
    files.append(dockerfile_path)

    ci_path = workflow_dir / "ci.yml"
    ci_path.write_text(_workflow_ci(), encoding="utf-8")
    files.append(ci_path)

    self_heal_path = workflow_dir / "ci-self-heal.yml"
    self_heal_path.write_text(_workflow_self_heal(), encoding="utf-8")
    files.append(self_heal_path)

    chart_path = repo / "helm" / "Chart.yaml"
    chart_path.write_text(_helm_chart_yaml(app_name), encoding="utf-8")
    files.append(chart_path)

    values_path = repo / "helm" / "values.yaml"
    values_path.write_text(_helm_values(state.image_ref_for_registry(), state.namespace), encoding="utf-8")
    files.append(values_path)

    deployment_path = helm_templates / "deployment.yaml"
    deployment_path.write_text(_helm_deployment(app_name, state.pull_secret_name), encoding="utf-8")
    files.append(deployment_path)

    argocd_path = argocd_dir / "application.yaml"
    argocd_path.write_text(_argocd_application(app_name, state.namespace), encoding="utf-8")
    files.append(argocd_path)

    return files
