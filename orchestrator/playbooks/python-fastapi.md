# Python FastAPI Playbook

## Detection
- requirements.txt contains fastapi and uvicorn.
- Entrypoint commonly app/main.py with `app = FastAPI()`.

## Dockerfile pattern
- Base image: python:3.12-slim.
- Install requirements from requirements.txt.
- Runtime: `uvicorn app.main:app --host 0.0.0.0 --port <port>`.

## Helm notes
- containerPort and service.port must match planner port.
- healthPath usually /health or /docs fallback checks.

## Common mistakes
- Using python -m http.server.
- Hardcoding port 8000 when app expects 8080.
