# Frontend React Playbook

## Detection
- package.json with react/react-dom.

## Dockerfile pattern
- Multi-stage: build with node, serve static bundle via nginx.

## Helm notes
- Service is usually HTTP only; health path can be `/`.

## Common mistakes
- Serving source tree instead of built assets.
- Not caching dependency install layers.
