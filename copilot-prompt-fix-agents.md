# Copilot Task — Convert All Agents from Templates to Real LLM Agents

> CONTEXT: The orchestrator was built with the right structure (graph, state, tools, artifacts,
> approve/resume flow) but ALL three agents (Planner, Dockerizer, Diagnose-Fix) are implemented as
> static templates/hardcoded functions. They do NOT call the LLM. They do NOT read the actual app
> repo. They return fixed values regardless of what app is given. This defeats the core product
> promise: "give it any app repo and it adapts."
>
> THIS TASK: Rewrite all three agents to be REAL LLM agents that use tools, read the repo, reason
> about what they find, and produce output specific to the actual app. The graph, state, tools,
> artifacts, approve/resume flow, and CLI stay unchanged.

---

## Step 1 — Audit and report

Before changing anything, read these files and list what each agent currently does:
- `orchestrator/agents/planner.py`
- `orchestrator/agents/dockerizer.py`
- `orchestrator/agents/diagnose_fix.py`
- `orchestrator/llm.py`

For each, answer: does it call the LLM? Does it use tools to read the repo? Does it produce
different output for different apps? If any agent is a static template, flag it.

---

## Step 2 — Ensure llm.py provides a usable chat interface

`llm.py` must expose a function the agents can call to get an LLM completion. It should support:
- Real mode: calls the configured provider (OpenAI / Anthropic / Bedrock) using the API key from env.
- Mock mode (`LLM_MODE=mock`): returns deterministic, realistic responses for testing.
- Tool/function calling support so agents can call tools in a loop.

If `llm.py` already does this, leave it. If it's a stub, implement it now. Use LangChain's
`ChatOpenAI` / `ChatAnthropic` or the LangGraph agent primitives — whichever matches the existing
imports.

---

## Step 3 — Rewrite the Planner agent (`orchestrator/agents/planner.py`)

The Planner's job: inspect the app repo and produce a `BuildPlan` specific to THIS app.

### Tools the Planner needs (create if they don't exist):
- `list_repo_files(path)` — list files/dirs at a path in the target repo
- `read_repo_file(path)` — read a file's contents from the target repo

### System prompt (embed in the agent):
```
You are the Planner agent. Your job is to inspect an application repository and produce a
structured BuildPlan. You have tools to list and read files in the repo.

Steps:
1. List the root directory to understand the project structure.
2. Look for dependency files: requirements.txt, package.json, pom.xml, build.gradle, go.mod, Gemfile.
3. Read the dependency file to identify the framework (FastAPI, Flask, Django, Express, Spring Boot, etc.).
4. Look for and read the entrypoint file (main.py, app.py, index.js, Application.java, etc.).
5. Identify the port the app listens on (look for port numbers in the entrypoint or config).
6. Identify the health endpoint if one exists (look for /health, /healthz, /status routes).
7. Identify the test command (look for pytest, jest, mvn test, go test in config or scripts).

If a pipeline-setup.yaml exists at the repo root, read it first and use its values for any
fields it provides. Only infer fields that are missing from the config.

Return a JSON object with these fields:
{
  "language": "python|node|java|go|...",
  "framework": "fastapi|flask|express|springboot|...",
  "entrypoint": "path/to/main/file",
  "port": 8080,
  "health_path": "/health",
  "test_command": "pytest",
  "dependencies_file": "requirements.txt",
  "notes": "anything unusual about this repo"
}

For each field, note whether it came from: config file, repo inspection, or inference.
If you cannot determine a field with confidence, set it to null and add a note.
Do NOT guess or hardcode — if you can't find evidence in the repo, say so.
```

### Behavior:
- The agent calls tools in a loop (list files → read dependency file → read entrypoint → conclude).
- Output is validated against the BuildPlan schema in `state.py`.
- In mock mode, the LLM returns a realistic but deterministic plan for the test fixture app.

---

## Step 4 — Rewrite the Dockerizer agent (`orchestrator/agents/dockerizer.py`)

The Dockerizer's job: produce a working Dockerfile for THIS app using the BuildPlan.

### Tools the Dockerizer needs:
- `read_repo_file(path)` — to inspect specific files if needed
- `write_file(path, content)` — to write the generated Dockerfile
- `build_image(context, tag)` — the existing deterministic build tool (to test if it builds)

### System prompt:
```
You are the Dockerizer agent. Given a BuildPlan and access to the app repo, generate a
production-quality multi-stage Dockerfile specific to this application.

Rules:
- Read the actual dependency file and entrypoint — do NOT assume what they contain.
- Match the framework to the correct runtime command:
    FastAPI → uvicorn app.main:app --host 0.0.0.0 --port <port>
    Flask → gunicorn app:app --bind 0.0.0.0:<port>
    Django → gunicorn project.wsgi:application --bind 0.0.0.0:<port>
    Express/Node → node <entrypoint>
    Spring Boot → java -jar target/*.jar
    Go → ./<binary>
- Use a slim/distroless base image appropriate for the language.
- Install dependencies from the correct file (requirements.txt, package.json, pom.xml, etc.).
- Run as a non-root user.
- Pin base image tags (e.g., python:3.12-slim, not python:latest).
- Do NOT bake secrets into the image.
- Add a HEALTHCHECK instruction if a health endpoint is known.
- Use multi-stage build where applicable (especially Java/Go) to keep the final image small.

Output the complete Dockerfile content. Explain your reasoning briefly.
```

### Behavior:
- Receives `state.build_plan` as input.
- Calls the LLM, which may read additional repo files via tools to clarify details.
- Writes the Dockerfile to the repo.
- Optionally triggers a test build; if it fails, iterates (up to 3 retries with the error message
  fed back to the LLM).
- In mock mode, returns a realistic Dockerfile matching the fixture app's framework.

---

## Step 5 — Rewrite the Diagnose-Fix agent (`orchestrator/agents/diagnose_fix.py`)

The Diagnose-Fix agent's job: when a step fails, read the error, investigate, and propose a fix.

### Tools:
- `read_repo_file(path)` — inspect generated or source files
- `list_repo_files(path)` — explore the repo
- `read_step_output(step_name)` — get the stdout/stderr of the failed step

### System prompt:
```
You are the Diagnose-Fix agent. A pipeline step has failed. Your job is to find the root cause
and propose a minimal fix.

You will receive:
- The name of the failed step (build, test, scan, deploy, healthcheck)
- The error output from that step
- Access to read files in the repo

Steps:
1. Read the error output carefully.
2. Identify the most likely root cause.
3. If you need more context, read the relevant files (Dockerfile, helm values, source code, etc.).
4. Propose a specific fix — which file to change and what to change.
5. Assess your confidence (0.0 to 1.0).

Rules:
- NEVER fix a failing test by deleting, skipping, or weakening the test.
- NEVER fix a scan finding by disabling the scanner.
- Only propose changes to generated artifacts (Dockerfile, Helm chart, CI workflow, ArgoCD manifest)
  or obvious config issues. Do NOT rewrite application source code.
- If your confidence is below 0.5, output a diagnosis only — do not propose a change.

Output a JSON object:
{
  "root_cause": "description of what went wrong",
  "confidence": 0.85,
  "fix": {
    "file": "path/to/file",
    "description": "what to change",
    "content": "the corrected file content or a diff"
  } | null,
  "action": "fix_proposed" | "diagnosis_only"
}
```

### Behavior:
- Receives the failed step name + error output.
- Calls the LLM with tools to investigate.
- Returns a validated FixProposal (from `state.py` schema).
- The guardrail that rejects test/scan-weakening fixes remains enforced in CODE as well as in the
  prompt (defense in depth) — do not remove it.

---

## Step 6 — Add test fixtures for two different app types

Create two fixture directories under `tests/fixtures/`:

### `tests/fixtures/fastapi-app/`
```
requirements.txt    → fastapi, uvicorn, pytest
app/
  __init__.py
  main.py           → FastAPI app with GET /health and POST /score
tests/
  test_api.py       → one passing test
```

### `tests/fixtures/node-express-app/`
```
package.json        → express, jest
src/
  index.js          → Express app on port 3000 with GET /health
tests/
  app.test.js       → one passing test
```

---

## Step 7 — Add agent diversity tests

In `tests/test_agents_mock.py` (or a new `tests/test_agent_diversity.py`):

```python
def test_planner_produces_different_plans():
    """Planner must detect FastAPI vs Node and return different BuildPlans."""
    plan_fastapi = run_planner("tests/fixtures/fastapi-app")
    plan_node = run_planner("tests/fixtures/node-express-app")
    assert plan_fastapi.language == "python"
    assert plan_fastapi.framework == "fastapi"
    assert plan_node.language == "node"
    assert plan_node.framework == "express"
    assert plan_fastapi.language != plan_node.language

def test_dockerizer_produces_different_dockerfiles():
    """Dockerizer must generate different Dockerfiles for different apps."""
    df_fastapi = run_dockerizer(fastapi_plan)
    df_node = run_dockerizer(node_plan)
    assert "uvicorn" in df_fastapi
    assert "node" in df_node
    assert df_fastapi != df_node  # CRITICAL — if same output, agent is a template

def test_dockerizer_never_uses_http_server():
    """Dockerfile must use the app's actual framework, not python http.server."""
    df = run_dockerizer(fastapi_plan)
    assert "http.server" not in df
    assert "uvicorn" in df
```

These tests MUST pass. If the Dockerizer produces the same Dockerfile for both apps, the test fails
— this prevents re-hardcoding a template.

---

## Step 8 — Verify end-to-end in mock mode

Run: `SANDBOX=1 LLM_MODE=mock pytest -q`

All existing tests (gates, guardrails) must still pass. The new diversity tests must also pass.
Then run the full orchestrator in mock mode against the FastAPI fixture:
`SANDBOX=1 LLM_MODE=mock python -m orchestrator.main run --repo tests/fixtures/fastapi-app`
and verify the generated Dockerfile contains `uvicorn`, not `http.server`.

---

## What NOT to change
- The graph (`graph.py`) — node structure, edges, approve/resume flow stay the same.
- The state (`state.py`) — schemas stay the same.
- The deterministic tools (`tools/`) — they are correct as-is.
- The artifacts/gitops layer — stays the same.
- The CLI (`main.py`) — stays the same.
- The guardrail code that rejects test/scan-weakening fixes — keep it.

## Summary
The structure is right. The agents are hollow. This task fills them with real LLM reasoning,
real tool use, and real tests that prevent regression to templates. After this, the orchestrator
will genuinely adapt to different apps — which is the entire product promise.
