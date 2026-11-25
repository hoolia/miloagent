{{/* Chart name */}}
{{- define "miloagent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fully qualified app name */}}
{{- define "miloagent.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* ServiceAccount of the MiloAgent pod; the bridge pod keeps the namespace default */}}
{{- define "miloagent.serviceAccountName" -}}
{{- default (include "miloagent.fullname" .) .Values.serviceAccount.name -}}
{{- end -}}

{{/* Common labels */}}
{{- define "miloagent.labels" -}}
app: {{ include "miloagent.name" . }}
app.kubernetes.io/name: {{ include "miloagent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/* Selector labels */}}
{{- define "miloagent.selectorLabels" -}}
app: {{ include "miloagent.name" . }}
{{- end -}}

{{/* Labels of the metrics Service, ServiceMonitor and PrometheusRule */}}
{{- define "miloagent.metricsLabels" -}}
app.kubernetes.io/name: {{ include "miloagent.name" . }}-metrics
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: {{ include "miloagent.name" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/* Bridge: name, labels and image. Its pods never carry the MiloAgent selector. */}}
{{- define "miloagent.bridge.fullname" -}}
{{- printf "%s-bridge" (include "miloagent.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "miloagent.bridge.selectorLabels" -}}
app: {{ include "miloagent.name" . }}-bridge
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "miloagent.bridge.labels" -}}
{{ include "miloagent.bridge.selectorLabels" . }}
app.kubernetes.io/name: {{ include "miloagent.name" . }}-bridge
app.kubernetes.io/component: bridge
app.kubernetes.io/part-of: {{ include "miloagent.name" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "miloagent.bridge.image" -}}
{{- printf "%s:%s" .Values.bridge.image.repository .Values.bridge.image.tag -}}
{{- end -}}

{{/* Secret with the dashboard password for the bridge server */}}
{{- define "miloagent.bridge.passwordSecret" -}}
{{- if .Values.bridge.server.passwordSecret.name -}}
{{- .Values.bridge.server.passwordSecret.name -}}
{{- else if .Values.env.MILO_WEB_PASS -}}
{{- include "miloagent.fullname" . -}}-env
{{- else if .Values.existingSecrets.env -}}
{{- .Values.existingSecrets.env -}}
{{- else -}}
{{- fail "bridge.server needs the dashboard password: set env.MILO_WEB_PASS, existingSecrets.env or bridge.server.passwordSecret.name" -}}
{{- end -}}
{{- end -}}
