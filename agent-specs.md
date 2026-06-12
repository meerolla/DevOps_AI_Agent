# Agent Specs — Pipeline Setup Orchestrator

> One section per agent. Agents do judgment only; deterministic work is delegated to tools.

---
## Orchestrator (thin supervisor)
- **Job:** decompose the goal, sequence steps, route to agents/tools, hold `PipelineState`, enforce
  approval gates. Plans and routes — does not do the work.
- **Inputs:** goal + repo reference.
- **Outputs:** a completed (or escalated) pipeline run + audit log.
- **Tools/sub-agents:** the 3 agents below + the deterministic tools.
- **Guardrails:** must pause at every gate; never executes a destructive tool before approval; routes
  failures to Diagnose-Fix rather than pushing ahead.
- **Stop:** app live and healthy, or escalation to a human with reason.

---
## Planner Agent
- **Job:** inspect the repo and produce a structured `BuildPlan`.
- **Inputs:** repo files.
- **Outputs:** `BuildPlan { language, framework, entrypoint, ports[], dependencies[], stateful,
  needs_db, test_command, notes }`.
- **Tools:** `list_repo_files`, `read_repo_file`.
- **Guardrails:** if it can't confidently determine a field, mark it `unknown` and flag for human —
  never guess silently. No code execution.
- **Eval:** on seeded sample repos, fields match the known ground truth.

---
## Dockerizer Agent
- **Job:** produce a working multi-stage Dockerfile from the `BuildPlan`, iterating until it builds.
- **Inputs:** `BuildPlan`, repo files.
- **Outputs:** a Dockerfile + the resulting image reference (after the deterministic build tool runs).
- **Tools:** `read_repo_file`, `write_file`, `build_image` (deterministic).
- **Guardrails:** non-root image; pinned base tags; no secrets baked in; bounded build retries. If it
  can't get a clean build, escalate with the build error.
- **Eval:** `docker build` succeeds and the container serves its healthcheck.

---
## Diagnose-Fix Agent
- **Job:** when a deterministic step (build/test/scan/deploy/healthcheck) fails, find the cause and
  propose a fix for that single step.
- **Inputs:** the failing step's output + relevant artifacts (`BuildPlan`, Dockerfile, logs, report).
- **Outputs:** `FixProposal { root_cause, confidence, change, retry_step }` or an escalation.
- **Tools:** read access to artifacts; `write_file` for proposed changes.
- **Guardrails:** never disables/weakens a test or scan to force a pass; below confidence threshold ->
  escalate; only proposes a change to the failing step, then the orchestrator retries that step.
- **Eval:** on seeded failures, identifies the correct cause and its proposed fix lets the step pass.

---
## Shared contract — PipelineState
```
PipelineState {
  goal, repo_ref
  build_plan: BuildPlan | null
  dockerfile_ref: str | null
  image_ref: str | null
  test_results: ... | null
  scan_report: ... | null
  manifests_ref: str | null
  approvals: { infra: bool, deploy: bool }
  step_status: { step -> pending|ok|failed|escalated }
  audit: AuditEntry[]
}
```
