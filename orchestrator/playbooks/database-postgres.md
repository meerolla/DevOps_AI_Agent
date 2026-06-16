# Database Postgres Playbook

## Detection
- psycopg/pg deps, migration configs, or postgres service references.

## Dockerfile pattern
- Keep app image separate from postgres runtime.

## Helm notes
- Use secrets for DB URL and credentials.

## Common mistakes
- Shipping local sqlite defaults to production.
- Missing readiness ordering for DB dependencies.
