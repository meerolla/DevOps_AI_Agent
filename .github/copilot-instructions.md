# Copilot Instructions — Pipeline Setup Orchestrator (demo 3)

> Project constitution for building this multi-agent system. Applies to every task.

## What this is
A thin LangGraph orchestrator coordinating three judgment agents (Planner, Dockerizer, Diagnose-Fix)
over deterministic tools (Terraform, Docker, test runner, Trivy, Helm, ArgoCD), to set up CI/CD and
deploy an app — with human approval gates on destructive steps. Built spec-first from `specs/` and
`agent-specs.md`; architecture in `architecture.md`.

## Tech stack (do not deviate)
- Python 3.12, LangGraph + LangChain, Pydantic v2, pytest. Mock LLM mode + SANDBOX mode required.
- Default target is on-prem: **k3s/k3d** cluster (a prerequisite, not provisioned here), **GHCR**
  registry (GitHub-token auth), OpenAI/Anthropic (or local) LLM. AWS/EKS + ECR + Bedrock + Terraform
  are an alternative path; on-prem `provision_infra` is just namespace + secrets.

## The core architectural rule (do not break)
**Agents do judgment; tools do execution; humans gate destructive steps.**
- LLM agents only for ambiguity (plan, dockerize, diagnose). No LLM calls inside `tools/`.
- Build/test/scan/provision/deploy are deterministic tools.
- The orchestrator (the graph) stays thin: routing, state, and gates only.

## Hard rules (enforce in CODE, with tests)
1. No destructive tool (terraform apply, deploy) runs unless the matching `state.approvals` flag is true.
2. `provision_infra` always produces a `terraform plan` for the gate before any apply.
3. Diagnose-Fix may never delete/skip/weaken a test or scan to force a pass.
4. Agents get scoped, read-mostly tools — no standing cloud-admin creds.
5. Bounded retries per step, then escalate. Audit every step + approval. Never log secrets.

## Python environment (always)
- Always work inside a project virtual environment at `./.venv`. Never install into system Python.
- First step of any setup or build task: create and activate it, then install deps:
  `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- All `pip`, `pytest`, and run commands assume the `.venv` is active. Add `.venv/` to `.gitignore`.

## Conventions
- Conform to `state.py` contracts and `agent-specs.md`; don't rename fields.
- Small, typed, individually testable agents and tools.
- Prefer the simplest implementation that meets acceptance criteria.

## When unsure
- Follow the specs and `architecture.md`. Pick the simplest compliant option and note assumptions in
  the PR description — don't pause for chat; this build is hands-off.
