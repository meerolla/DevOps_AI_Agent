# Multi-Agent Orchestration

> Agent Skill at `.github/skills/multi-agent-orchestration/SKILL.md`. Loaded when building the graph,
> agents, tools, or state. The project's "how to do this well" for the orchestrator pattern.

## When to use
When implementing `graph.py`, the agents in `agents/`, the deterministic `tools/`, or `state.py`.

## The pattern (orchestrator-worker)
- The orchestrator is a LangGraph state machine: nodes are steps, edges are routing, a typed
  `PipelineState` is the single source of truth. Keep it thin — no business logic, just routing,
  state updates, and gates.
- Each judgment agent is a small unit with a clear input/output contract from `agent-specs.md`. It
  reasons; it does not execute infra/build/deploy itself.
- Each tool is a deterministic, typed function. No LLM inside a tool.

## Doing it well
- **Structured hand-offs only.** Agents read/write fields on `PipelineState`; never pass freeform chat
  between steps. Validate state shape at each node boundary.
- **Validate, then route.** After build/test/scan/health, check the result and branch: ok -> next;
  fail -> Diagnose-Fix -> retry the same node (bounded). Don't restart the whole graph.
- **Human gates via `interrupt()`.** Pause before provision and deploy; resume only after the approval
  flag is set in state. The destructive tool must assert the flag itself, too (defense in depth).
- **Idempotency + checkpointing.** Use LangGraph checkpointing so a resumed run continues from the last
  good node rather than repeating work.

## Safety (enforce in code, add tests)
- Destructive tools refuse to run without the matching `state.approvals` flag — unit-test the refusal.
- `provision_infra` returns a `terraform plan` for the gate; `apply` is a separate, post-approval call.
- Diagnose-Fix proposals that delete/skip/weaken a test or scan are rejected — unit-test the rejection.
- Agents are constructed with scoped, read-mostly tools; no cloud-admin creds in agent context.

## Testing
- Unit-test each agent (mock LLM) and each tool (sandbox).
- `test_gates.py`: apply/deploy do not run without approval.
- End-to-end in SANDBOX + mock: full run reaches a healthy deploy, recovering a seeded test failure.
