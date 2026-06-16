# Java Spring Boot Playbook

## Detection
- pom.xml or build.gradle with spring-boot dependency.

## Dockerfile pattern
- Multi-stage build (maven/gradle builder + JRE runtime).
- Runtime: `java -jar target/*.jar`.

## Helm notes
- Default app port often 8080 unless configured otherwise.

## Common mistakes
- Shipping full build toolchain in runtime image.
- Missing JAVA_OPTS handling.
