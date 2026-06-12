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
python -m orchestrator.main run --repo ./tests/fixtures/sample-repo --goal "set up CI/CD and deploy"
```

## Test

```bash
SANDBOX=1 LLM_MODE=mock pytest -q
```
