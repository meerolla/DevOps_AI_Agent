from pathlib import Path

from orchestrator.validators import validate_generated_artifacts


def _write_minimal_valid_artifacts(repo: Path) -> None:
    (repo / "deploy" / "helm" / "templates").mkdir(parents=True, exist_ok=True)
    (repo / "deploy" / "argocd").mkdir(parents=True, exist_ok=True)
    (repo / "deploy" / "helm" / "values.yaml").write_text(
        """image:
  repository: ghcr.io/demo/sample
  tag: latest
containerPort: 8080
healthPath: /health
service:
  type: ClusterIP
  port: 8080
""",
        encoding="utf-8",
    )
    (repo / "deploy" / "helm" / "templates" / "deployment.yaml").write_text(
        """apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - name: app
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          livenessProbe:
            httpGet:
              path: {{ .Values.healthPath | default "/health" }}
              port: {{ .Values.containerPort }}
          readinessProbe:
            httpGet:
              path: {{ .Values.healthPath | default "/health" }}
              port: {{ .Values.containerPort }}
""",
        encoding="utf-8",
    )
    (repo / "deploy" / "argocd" / "application.yaml").write_text(
        """apiVersion: argoproj.io/v1alpha1
kind: Application
spec:
  source:
    repoURL: https://github.com/acme/demo.git
""",
        encoding="utf-8",
    )
    (repo / "Dockerfile").write_text("FROM python:3.12-slim\nEXPOSE 8080\n", encoding="utf-8")


def test_validate_generated_artifacts_success_without_helm_binary(tmp_path: Path) -> None:
    _write_minimal_valid_artifacts(tmp_path)
    errors = validate_generated_artifacts(str(tmp_path))
    assert errors == []


def test_validate_generated_artifacts_invalid_yaml(tmp_path: Path) -> None:
    _write_minimal_valid_artifacts(tmp_path)
    (tmp_path / "deploy" / "argocd" / "application.yaml").write_text("spec:\n  source: [", encoding="utf-8")
    errors = validate_generated_artifacts(str(tmp_path))
    assert any("Invalid YAML" in err for err in errors)


def test_validate_generated_artifacts_invalid_repo_url(tmp_path: Path) -> None:
    _write_minimal_valid_artifacts(tmp_path)
    (tmp_path / "deploy" / "argocd" / "application.yaml").write_text(
        """apiVersion: argoproj.io/v1alpha1
kind: Application
spec:
  source:
    repoURL: file://.
""",
        encoding="utf-8",
    )
    errors = validate_generated_artifacts(str(tmp_path))
    assert any("repoURL is invalid" in err for err in errors)


def test_validate_generated_artifacts_port_mismatch(tmp_path: Path) -> None:
    _write_minimal_valid_artifacts(tmp_path)
    (tmp_path / "deploy" / "helm" / "values.yaml").write_text(
        """image:
  repository: ghcr.io/demo/sample
  tag: latest
containerPort: 8080
service:
  type: ClusterIP
  port: 9090
""",
        encoding="utf-8",
    )
    errors = validate_generated_artifacts(str(tmp_path))
    assert any("Port mismatch" in err for err in errors)


def test_validate_generated_artifacts_missing_probes(tmp_path: Path) -> None:
    _write_minimal_valid_artifacts(tmp_path)
    (tmp_path / "deploy" / "helm" / "templates" / "deployment.yaml").write_text(
        "apiVersion: apps/v1\nkind: Deployment\nspec: {}\n",
        encoding="utf-8",
    )
    errors = validate_generated_artifacts(str(tmp_path))
    assert any("livenessProbe" in err for err in errors)
    assert any("readinessProbe" in err for err in errors)
