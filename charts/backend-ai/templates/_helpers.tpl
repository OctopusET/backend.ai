{{/* Chart name */}}
{{- define "backend-ai.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fully qualified app name */}}
{{- define "backend-ai.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "backend-ai.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "backend-ai.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "backend-ai.labels" -}}
helm.sh/chart: {{ include "backend-ai.chart" . }}
{{ include "backend-ai.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "backend-ai.selectorLabels" -}}
app.kubernetes.io/name: {{ include "backend-ai.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Container image (global repo:tag, tag defaults to appVersion) */}}
{{- define "backend-ai.image" -}}
{{- $tag := .Values.global.image.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" .Values.global.image.repository $tag -}}
{{- end -}}

{{- define "backend-ai.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "backend-ai.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Infra service hostnames: explicit override, else bundled service, else fail in prod */}}
{{- define "backend-ai.dbHost" -}}
{{- if .Values.config.db.host -}}{{ .Values.config.db.host }}
{{- else if .Values.postgresql.enabled -}}{{ printf "%s-postgresql" (include "backend-ai.fullname" .) }}
{{- else -}}{{ fail "config.db.host is required when postgresql.enabled=false" }}{{- end -}}
{{- end -}}

{{- define "backend-ai.redisHost" -}}
{{- if .Values.config.redis.host -}}{{ .Values.config.redis.host }}
{{- else if .Values.redis.enabled -}}{{ printf "%s-redis" (include "backend-ai.fullname" .) }}
{{- else -}}{{ fail "config.redis.host is required when redis.enabled=false" }}{{- end -}}
{{- end -}}

{{- define "backend-ai.etcdHost" -}}
{{- if .Values.config.etcd.host -}}{{ .Values.config.etcd.host }}
{{- else if .Values.etcd.enabled -}}{{ printf "%s-etcd" (include "backend-ai.fullname" .) }}
{{- else -}}{{ fail "config.etcd.host is required when etcd.enabled=false" }}{{- end -}}
{{- end -}}

{{/* Secret name (existing or generated) */}}
{{- define "backend-ai.secretName" -}}
{{- default (include "backend-ai.fullname" .) .Values.secrets.existingSecret -}}
{{- end -}}

{{/* envFrom block shared by all Backend.AI services */}}
{{- define "backend-ai.envFrom" -}}
- configMapRef:
    name: {{ include "backend-ai.fullname" . }}-env
- secretRef:
    name: {{ include "backend-ai.secretName" . }}
{{- end -}}
