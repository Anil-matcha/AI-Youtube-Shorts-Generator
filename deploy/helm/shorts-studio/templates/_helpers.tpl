{{- define "shorts-studio.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "shorts-studio.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- include "shorts-studio.name" . }}
{{- end }}
{{- end }}

{{- define "shorts-studio.labels" -}}
app.kubernetes.io/name: {{ include "shorts-studio.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "shorts-studio.selectorLabels" -}}
app.kubernetes.io/name: {{ include "shorts-studio.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
