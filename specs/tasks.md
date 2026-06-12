# Tasks — Pipeline Setup Orchestrator (build)

> Spec 3 of 3. Ordered checklist for the Copilot build agent. Tests green before moving on.

## Build tasks
- [ ] T1. Scaffold `orchestrator/` + `tests/`, `requirements.txt` (langgraph, langchain, pydantic,
      pytest), `README.md` with run/test commands. Create a `./.venv` (`python3.12 -m venv .venv`),
      activate it, install deps into it, and add `.venv/` to `.gitignore`. (design: Stack, Layout)
- [ ] T2. Implement `state.py`: `PipelineState`, `BuildPlan`, `FixProposal`, artifact + audit models.
- [ ] T3. Implement `llm.py` (provider + deterministic mock) and `audit.py` (secret-safe log). (US6, US7)
- [ ] T4. Implement deterministic tools in `tools/` (infra, build, test, scan, deploy, health), each a
      typed function shelling out, sandbox-aware. `provision_infra` returns a `plan` before any apply. (US3)
- [ ] T5. Implement the Planner agent. (US1)
- [ ] T6. Implement the Dockerizer agent (loops with `build_image` until clean; guardrails). (US2)
- [ ] T7. Implement the Diagnose-Fix agent, incl. the code-level rule blocking test/scan-weakening fixes. (US4)
- [ ] T8. Implement `graph.py`: nodes + conditional failure edges to Diagnose-Fix + `interrupt()` gates
      before provision and deploy; destructive tools guarded by `state.approvals`. (US3, US4, US5)
- [ ] T9. Implement `main.py` CLI: `run --repo --goal`. (US7)
- [ ] T10. Add `tests/fixtures/sample-repo/` with a seeded known test failure.
- [ ] T11. `tests/test_gates.py`: provision/deploy do NOT run without recorded approval. (US5)
- [ ] T12. `tests/test_agents_mock.py`: full run in SANDBOX + mock mode reaches a healthy deploy,
      recovering the seeded test failure via Diagnose-Fix. (Acceptance)
- [ ] T13. Ensure `SANDBOX=1 LLM_MODE=mock pytest -q` passes.

## Guardrails for the build agent
- Conform to `state.py` contracts and `agent-specs.md`; do not rename fields.
- Agents = judgment only; all execution goes through `tools/`. No LLM calls inside tools.
- The approval-gate and "never weaken a test/scan" rules must be enforced in CODE, with tests.
- Keep the orchestrator thin: routing/state/gates live in the graph, not in the agents.
- If ambiguous, pick the simplest compliant option; note assumptions in the PR description.

## Done
- [ ] All tasks checked, sandbox+mock run reaches healthy deploy with gates honored, PR merged.
