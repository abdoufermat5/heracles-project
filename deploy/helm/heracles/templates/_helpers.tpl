{{- define "heracles.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "heracles.fullname" -}}
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

{{- define "heracles.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ include "heracles.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Selector labels of one component: web or worker. */}}
{{- define "heracles.selectorLabels" -}}
app.kubernetes.io/name: {{ include "heracles.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "heracles.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "heracles.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "heracles.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{- define "heracles.secretName" -}}
{{- required "secrets.existingSecret is required: the Secret holding bind_password" .Values.secrets.existingSecret -}}
{{- end -}}

{{/* Environment shared by the web and worker containers. */}}
{{- define "heracles.env" -}}
- name: HERACLES_CONFIG
  value: /etc/heracles/heracles.yaml
- name: HERACLES_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ default (include "heracles.secretName" .) .Values.secrets.databaseUrl.existingSecret }}
      key: {{ .Values.secrets.databaseUrl.key }}
{{- end -}}

{{/* Volumes and mounts shared by the web and worker pods. */}}
{{- define "heracles.volumes" -}}
- name: config
  configMap:
    name: {{ include "heracles.fullname" . }}
- name: secrets
  secret:
    secretName: {{ include "heracles.secretName" . }}
    defaultMode: 0440
- name: data
  emptyDir: {}
- name: tmp
  emptyDir: {}
{{- end -}}

{{- define "heracles.volumeMounts" -}}
- name: config
  mountPath: /etc/heracles/heracles.yaml
  subPath: heracles.yaml
  readOnly: true
- name: secrets
  mountPath: /etc/heracles/secrets
  readOnly: true
- name: data
  mountPath: /var/lib/heracles
- name: tmp
  mountPath: /tmp
{{- end -}}
