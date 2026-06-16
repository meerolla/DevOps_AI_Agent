# Helm Service Template Reference

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "<chart>.fullname" . }}
spec:
  type: {{ .Values.service.type | default "ClusterIP" }}
  ports:
    - port: {{ .Values.service.port | default .Values.containerPort }}
      targetPort: {{ .Values.containerPort }}
      protocol: TCP
      name: http
  selector:
    {{- include "<chart>.selectorLabels" . | nindent 4 }}
```

## Rules
- Both `port` and `targetPort` come from values.
- Keep list indentation valid under `ports:`.
