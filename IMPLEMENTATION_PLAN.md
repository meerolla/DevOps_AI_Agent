## Plan: Real LLM Agents First

The product promise is adaptation across app repos. Priority is to make Planner, Dockerizer, and Diagnose-Fix real LLM agents that use repo-reading tools and produce app-specific outputs. Existing graph/state/tools/CLI contracts remain unchanged.

**Current status**
1. Phase2 (CI hardening): Implemented.
2. Phase3 (git non-interactive auth diagnostics): Implemented.
3. AR1 (real LLM agents): Next highest priority.
4. H1 (runtime correctness guardrails): Immediate follow-up after AR1.
5. Phase4 (multi-component): After AR1 and H1.
6. Phase1 (TA/TB targets/EKS): After Phase4.

**AR1: Real Agent Core**
1. Planner rewrite.
- Planner must inspect the target repo using file listing and file reading tools.
- Planner returns BuildPlan with evidence-based language/framework/entrypoint/ports/test command.
- Planner must use config values from pipeline-setup.yaml when present, infer only missing fields.

2. Dockerizer rewrite.
- Dockerizer must generate framework-specific Dockerfile content.
- Dockerizer uses BuildPlan plus repo evidence and validates with deterministic build retries.
- Dockerizer must not emit one-size-fits-all runtime commands.

3. Diagnose-Fix rewrite.
- Diagnose-Fix must investigate failed-step output and relevant artifacts before proposing fix.
- Preserve code guardrail: no test/scan weakening and no application-source rewrites.

4. llm.py interface hardening.
- Keep provider mode and mock mode.
- Ensure agents have usable completion API and tool-calling loop support.

**H1: Runtime correctness guardrails**
1. Block generic runtime mismatches for detected frameworks (for example FastAPI should not run as directory server).
2. Strengthen deployment health validation for obvious mis-serve behavior.
3. Keep deterministic guardrails as defense in depth even when provider mode is enabled.

**Test strategy**
1. Add app-diversity fixtures:
- FastAPI fixture app.
- Node/Express fixture app.

2. Add anti-template diversity tests:
- Planner produces different plans for different app types.
- Dockerizer produces different Dockerfiles for different app types.
- FastAPI Dockerfile must not include `python -m http.server`.

3. Keep existing gate/safety tests green.

**Verification gates**
1. `SANDBOX=1 LLM_MODE=mock pytest -q` passes including new diversity tests.
2. Mock end-to-end run on FastAPI fixture yields uvicorn-style runtime.
3. Mock end-to-end run on Node fixture yields node runtime.
4. Provider-mode smoke test confirms real-provider behavior with `LLM_MODE=provider` and `OPENAI_API_KEY`.

**Out of scope for AR1/H1**
1. Graph node/edge redesign.
2. PipelineState contract redesign.
3. Deterministic tools rewrite.
4. Multi-component orchestration logic (Phase4).
5. Target abstraction implementation (Phase1 TA/TB path).
