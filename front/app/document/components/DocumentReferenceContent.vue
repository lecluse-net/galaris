<template>
  <MindMapEditor :model-value="document.payload.text ?? ''"
    :document-title="document.title" :resource-agent-id="agentId" :resolve-image="resolveImage" readonly embedded />
</template>
<script setup lang="ts">
import { defineAsyncComponent } from 'vue'
import type { DocumentDetail } from '../types'

defineProps<{ document: DocumentDetail; agentId?: number | null; resolveImage: (documentId: string, attachmentId: string) => Promise<Blob> }>()
const MindMapEditor = defineAsyncComponent(() => import('../mindmap/MindMapEditor.vue'))
</script>
