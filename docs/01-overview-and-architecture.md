# Overview and Architecture

Pipeline Setup Orchestrator is a thin multi-agent system that takes a fresh application repository, sets up CI/CD, deploys to Kubernetes, and keeps the process safe with human approval gates.

## Product Summary

DevOps AI Agent is positioned as: from app repo to live deployment, automatically, with spec-driven pipeline setup and self-healing.

The orchestrator coordinates three judgment agents over deterministic tools:
- Planner agent
- Dockerizer agent
- Diagnose-Fix agent

Deterministic execution runs through Docker, Trivy, Helm, ArgoCD, and cluster tooling. Humans approve destructive steps.

## How It Is Delivered

The system is delivered through three surfaces:
1. CLI tool (`pipeline-setup run ...`) installed via pip or pipx on a machine with cluster access.
2. GitHub Action (`.github/workflows/ci-self-heal.yml`) committed into the target app repo.
3. Repo configuration (`.github/copilot-instructions.md`, skills, and agents) in the orchestrator repo.

## Core Principle

Agents do judgment. Tools do execution. Humans gate destructive steps.

- LLM agents are used only where there is ambiguity.
- Deterministic tools run provision, build, test, scan, deploy, and healthcheck.
- Destructive or expensive actions pause for human approval.

## Components

### Orchestrator (thin supervisor)

The orchestrator decomposes goals, sequences steps, routes work, carries shared state, and enforces approval gates. It plans and routes; it does not perform deterministic work itself.

### Judgment agents

1. Planner: inspects repo and produces BuildPlan (language, framework, ports, dependencies, stateful, DB need, test command).
2. Dockerizer: generates a working multi-stage Dockerfile.
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
   -> [agent: Planner]      inspect repo            -> BuildPlan
   -> [agent: Dockerizer]   write Dockerfile        -> Dockerfile
   -> [tool: build_image]   docker build            -> image ref     (fail -> Diagnose-Fix -> retry)
   -> [tool: run_tests]     run test command        -> results       (fail -> Diagnose-Fix -> retry)
   -> [tool: scan_image]    Trivy scan              -> report        (high CVE -> Diagnose-Fix / GATE)
   -> [GATE] human approves infra change set
   -> [tool: provision_infra] apply change set      -> infra
   -> [GATE] human approves deploy
   -> [tool: deploy]        Helm + ArgoCD sync      -> live
   -> [tool: healthcheck]   probe service           (unhealthy -> Diagnose-Fix -> recommend rollback)
```

## Diagram

```text
                         +---------------------------+
                         |       ORCHESTRATOR        |   plans, routes, holds state,
                         |   (thin supervisor)       |   enforces approval gates
                         +-------------+-------------+
            judgment           |       |       |            execution
        +------------------+---+   +---+---+   +--+------------------------+
        |                  |       |       |      |                        |
   [Planner]        [Dockerizer]  [Diagnose-Fix]  |   deterministic tools  |
    inspect repo     write image    fix failures  |  provision/build/test/ |
                                                   |  scan/deploy/health    |
                                                   +-----------+------------+
                                                               |
                                                  [GATE] human approves
                                                  destructive steps
```

## Failure Handling

- Validate after every step.
- On failure, route to Diagnose-Fix, retry only the failed step.
- Use bounded retries.
- Escalate with diagnosis when retries are exhausted.
- Keep steps idempotent and checkpointed.

## Safety and Blast Radius

- No standing cloud-admin credentials for agents.
- Destructive operations run only via gated tool calls.
- Humans review change set before apply.
- Deploy path is GitOps-oriented through ArgoCD.
- Audit log records steps and approvals.

## Demo and Sandbox Mode

For demos, use local k3s or k3d and SANDBOX mode to keep runs reproducible and low-risk.

## Scope and Evolution

Current implementation works end-to-end for a Python web app on k3s. Architecture is intended to extend to more languages and deployment targets.

See:
- setup and run procedures: docs/02-setup-and-operations.md
- demo script and roadmap: docs/03-demo-and-roadmap.md
