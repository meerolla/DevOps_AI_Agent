# Helm Deployment Template Reference

## Correct YAML structure (note indentation)
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "<chart>.fullname" . }}
  labels:
    {{- include "<chart>.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "<chart>.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "<chart>.selectorLabels" . | nindent 8 }}
    spec:
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          ports:
            - containerPort: {{ .Values.containerPort }}
          livenessProbe:
            httpGet:
              path: {{ .Values.healthPath | default "/health" }}
              port: {{ .Values.containerPort }}
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: {{ .Values.healthPath | default "/health" }}
              port: {{ .Values.containerPort }}
            initialDelaySeconds: 5
            periodSeconds: 10
```

## Rules
- All list items are indented two spaces under parent key.
- Use `.Values.containerPort` for runtime/listener ports; do not hardcode.
- Include both liveness and readiness probes.
- Do not use `.Values.namespace`; rely on release namespace.
