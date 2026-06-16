# PHP Apache Playbook

## Detection
- composer.json and php files with Apache expectations.

## Dockerfile pattern
- Base image: php:8.x-apache.
- Copy application under /var/www/html.

## Helm notes
- Probe path should target app health route if available.

## Common mistakes
- Wrong document root.
- Missing required PHP extensions.
