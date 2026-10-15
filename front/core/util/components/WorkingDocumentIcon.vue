<template>
  <component :is="workingDocumentIcon" v-if="workingDocumentIcon" :document-id="documentId" :title="title" :size="size" :readonly="readonly" />
  <DocumentFileIcon v-else :size="size" />
</template>
<script setup lang="ts">
import { workingDocumentIcon } from '../workingDocumentEditor'
import DocumentFileIcon from './DocumentFileIcon.vue'
const { documentId, title, size = '22px', readonly = false } = defineProps<{ documentId: string; title: string; size?: string; readonly?: boolean }>()
</script>
