<template>
  <DocumentApplication v-if="app" :app="app" :document-id="documentId" :revision="revision" :ready="ready" :register-snapshot="registerSnapshot" />
  <div v-else class="q-pa-md" role="alert">{{ t('documents.apps.invalid') }}</div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RegisterDocumentCapture } from '@/core/util'
import { parseDocumentApp } from '../documentApps'
import DocumentApplication from './DocumentApplication.vue'
const { source, language, documentId, revision, ready, registerSnapshot } = defineProps<{ source: string; language: string; documentId: string; revision: number; ready: boolean; registerSnapshot?: RegisterDocumentCapture }>()
const { t } = useI18n()
const app = computed(() => language === 'galaris-raw-html' ? { id: 'document-html', title: t('documents.types.html'), html: source, datasets: rawDatasets(source) } : parseDocumentApp(source))
function rawDatasets(html: string): NonNullable<import('../documentApps').DocumentApp['datasets']> {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  return Object.fromEntries([...doc.querySelectorAll('[data-dataset]')].map(element => [
    element.getAttribute('data-dataset-alias') ?? 'entries',
    { uri: element.getAttribute('data-dataset') ?? '', access: element.getAttribute('data-dataset-access') === 'read' ? 'read' : element.getAttribute('data-dataset-access') === 'write' || element.tagName === 'FORM' ? 'write' : 'read' },
  ]))
}
</script>
