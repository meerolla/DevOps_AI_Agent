# Node Express Playbook

## Detection
- package.json contains express dependency.
- Entrypoint in main or scripts.start.

## Dockerfile pattern
- Base image: node:20-slim.
- Install with npm ci (or npm install fallback).
- Runtime: `node <entrypoint>`.

## Helm notes
- containerPort derived from detected listener port.

## Common mistakes
- Copying only source without package.json.
- Hardcoded health path mismatch.
