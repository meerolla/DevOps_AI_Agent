from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from orchestrator.tools._shell import run_command


def _find_yaml_files(repo_path: Path) -> list[Path]:
    return [p for p in repo_path.rglob("*") if p.is_file() and p.suffix in {".yml", ".yaml"}]


def _contains_helm_template_markers(text: str) -> bool:
    return "{{" in text or "}}" in text


def _extract_values_container_port(values_text: str) -> int | None:
    match = re.search(r"(?m)^containerPort:\s*(\d+)", values_text)
    if not match:
        return None
    return int(match.group(1))


def _extract_values_service_port(values_text: str) -> int | None:
    match = re.search(r"(?ms)^service:\s*\n(?:[ \t]+.*\n)*?[ \t]+port:\s*(\d+)", values_text)
    if not match:
        return None
    return int(match.group(1))


def _extract_docker_expose(dockerfile_text: str) -> int | None:
    match = re.search(r"(?m)^EXPOSE\s+(\d+)", dockerfile_text)
    if not match:
        return None
    return int(match.group(1))


def validate_generated_artifacts(repo_path: str) -> list[str]:
    """Returns a list of error messages. Empty list means validation succeeded."""
    errors: list[str] = []
    repo = Path(repo_path)

    # 1) YAML validity for non-templated yaml files
    for yaml_file in _find_yaml_files(repo):
        text = yaml_file.read_text(encoding="utf-8", errors="replace")
        if _contains_helm_template_markers(text):
            continue
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            rel = str(yaml_file.relative_to(repo)).replace("\\", "/")
            errors.append(f"Invalid YAML in {rel}: {exc}")

    # 2) helm template render check, if helm installed
    helm_dir = repo / "deploy" / "helm"
    if helm_dir.exists() and shutil.which("helm"):
        ok, output = run_command(f"helm template test {helm_dir}", cwd=repo)
        if not ok:
            errors.append(f"helm template failed: {output}")

    # 3) argocd repoURL validation
    argocd_file = repo / "deploy" / "argocd" / "application.yaml"
    if argocd_file.exists():
        try:
            app = yaml.safe_load(argocd_file.read_text(encoding="utf-8")) or {}
            repo_url = (((app.get("spec") or {}).get("source") or {}).get("repoURL") or "").strip()
            if not repo_url or repo_url.startswith("file://"):
                errors.append(f"ArgoCD repoURL is invalid: '{repo_url}' — must be a Git URL")
        except yaml.YAMLError as exc:
            errors.append(f"Invalid YAML in deploy/argocd/application.yaml: {exc}")

    # 4) port consistency: values containerPort and service.port and Dockerfile EXPOSE
    # For multi-component repos values.yaml uses a nested components: block — skip the
    # single-component checks in that case to avoid false positives.
    values_file = repo / "deploy" / "helm" / "values.yaml"
    dockerfile = repo / "Dockerfile"
    if values_file.exists():
        text = values_file.read_text(encoding="utf-8", errors="replace")
        is_multi_component = re.search(r"(?m)^components:\s*$", text) is not None
        if not is_multi_component:
            container_port = _extract_values_container_port(text)
            service_port = _extract_values_service_port(text)
            if container_port is None:
                errors.append("Missing containerPort in deploy/helm/values.yaml")
            if service_port is None:
                errors.append("Missing service.port in deploy/helm/values.yaml")
            if container_port is not None and service_port is not None and container_port != service_port:
                errors.append(
                    f"Port mismatch in deploy/helm/values.yaml: containerPort={container_port} service.port={service_port}"
                )
            if dockerfile.exists() and container_port is not None:
                expose = _extract_docker_expose(dockerfile.read_text(encoding="utf-8", errors="replace"))
                if expose is not None and expose != container_port:
                    errors.append(
                        f"Port mismatch: Dockerfile EXPOSE={expose} does not match deploy/helm/values.yaml containerPort={container_port}"
                    )

    # 5) deployment probes exist
    deployment_template = repo / "deploy" / "helm" / "templates" / "deployment.yaml"
    if deployment_template.exists():
        dep = deployment_template.read_text(encoding="utf-8", errors="replace")
        if "livenessProbe:" not in dep:
            errors.append("Missing livenessProbe in deploy/helm/templates/deployment.yaml")
        if "readinessProbe:" not in dep:
            errors.append("Missing readinessProbe in deploy/helm/templates/deployment.yaml")

    return errors
