# Database MySQL Playbook

## Detection
- mysql client deps, migration scripts, or docker-compose mysql service references.

## Dockerfile pattern
- App images should not bundle mysql server.
- Use external service or managed chart.

## Helm notes
- Configure env/secret-driven connection string.

## Common mistakes
- Hardcoding root credentials.
- Treating DB container as app container.
