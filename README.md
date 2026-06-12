# Pipeline Setup Orchestrator

A thin multi-agent orchestrator for CI/CD and deploy setup.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python -m orchestrator.main run --repo ./tests/fixtures/sample-repo --cluster default --registry ghcr.io/demo/sample --namespace my-app --goal "set up CI/CD and deploy"
python -m orchestrator.main approve --repo ./tests/fixtures/sample-repo --step infra
python -m orchestrator.main resume --repo ./tests/fixtures/sample-repo
```

## Test

```bash
SANDBOX=1 LLM_MODE=mock pytest -q
```
