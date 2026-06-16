# Overview and Architecture

Pipeline Setup Orchestrator is a thin multi-agent system that takes an application repository, sets up CI/CD, deploys to Kubernetes, and enforces safety with human approval gates.

## Product Summary

DevOps AI Agent is positioned as: from app repo to live deployment, automatically, with spec-driven orchestration and safe recovery.

The orchestrator coordinates three judgment agents over deterministic tools:
- Planner
- Dockerizer
- Diagnose-Fix

Deterministic execution runs through Docker, Trivy, Helm, ArgoCD, and cluster tooling. Humans approve destructive steps.

## Core Principle

Agents do judgment. Tools do execution. Humans gate destructive steps.

- LLM agents reason where ambiguity exists.
- Deterministic tools run provision, build, test, scan, deploy, and healthcheck.
- Destructive or expensive actions pause for human approval.

## Agent Reality Contract

This project does not treat agents as static templates. Agent outputs must be app-specific and evidence-based.

1. Planner contract
- Must inspect repo files using read/list capabilities.
- Must identify language/framework/entrypoint/ports/tests from evidence.
- Must mark unknowns explicitly rather than guessing.

2. Dockerizer contract
- Must generate framework-specific Dockerfiles from the current BuildPlan and repo evidence.
- Must not default to generic runtime commands that ignore app type.
- Must validate through deterministic build attempts with bounded retries.

3. Diagnose-Fix contract
- Must investigate failed-step output and relevant artifacts before proposing a fix.
- Must preserve guardrails: never weaken tests/scans, never rewrite app source code.

## Components

### Orchestrator (thin supervisor)

The orchestrator decomposes goals, sequences steps, routes work, carries shared state, and enforces approval gates. It does not perform deterministic work itself.

### Judgment agents

1. Planner: inspects repo and produces BuildPlan (language, framework, ports, dependencies, stateful, DB need, test command).
2. Dockerizer: generates a working Dockerfile specific to the app and validates buildability.
3. Diagnose-Fix: investigates failed deterministic steps and proposes safe remediation or escalation.

### Deterministic tools

- provision_infra
- build_image
- run_tests
- scan_image
- deploy
- healthcheck

### Shared state

A typed PipelineState carries plan, Dockerfile reference, image reference, scan report, manifests, approvals, and step status.

## End-to-End Flow

```text
[orchestrator] receive goal + repo
   -> [agent: Planner]      inspect repo via tools        -> BuildPlan
   -> [agent: Dockerizer]   generate app-specific image   -> Dockerfile
   -> [tool: build_image]   docker build                  -> image ref     (fail -> Diagnose-Fix -> retry)
   -> [tool: run_tests]     run test command              -> results       (fail -> Diagnose-Fix -> retry)
   -> [tool: scan_image]    Trivy scan                    -> report        (high CVE -> Diagnose-Fix / GATE)
   -> [GATE] human approves infra change set
   -> [tool: provision_infra] apply change set            -> infra
   -> [GATE] human approves deploy
   -> [tool: deploy]        Helm + ArgoCD sync            -> live
   -> [tool: healthcheck]   probe service                 (unhealthy -> Diagnose-Fix -> recommend rollback)
```

## Safety and Blast Radius

- No standing cloud-admin credentials for agents.
- Destructive operations run only via gated tool calls.
- Humans review change set before apply.
- Deploy path is GitOps-oriented through ArgoCD.
- Audit log records steps and approvals.

## Scope and Evolution

Immediate architecture priority is Real LLM Agent Core: tool-using Planner, Dockerizer, and Diagnose-Fix with app-diverse behavior and anti-template regression tests.

See:
- setup and run procedures: docs/02-setup-and-operations.md
- demo script and roadmap: docs/03-demo-and-roadmap.md
