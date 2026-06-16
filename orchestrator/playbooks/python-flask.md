# Python Flask Playbook

## Detection
- requirements.txt contains flask.
- Entrypoint often app.py or wsgi.py.

## Dockerfile pattern
- Base image: python:3.12-slim.
- Runtime: gunicorn `app:app --bind 0.0.0.0:<port>`.

## Helm notes
- Expose selected app port and wire probes.

## Common mistakes
- Using Flask dev server in production.
- Missing health probes.
