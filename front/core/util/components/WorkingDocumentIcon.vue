<template>
  <component :is="workingDocumentIcon" v-if="workingDocumentIcon" :document-id="documentId" :title="title" :size="size" />
  <q-icon v-else name="description" :size="size" />
</template>
<script setup lang="ts">
import { workingDocumentIcon } from '../workingDocumentEditor'
const { documentId, title, size = '22px' } = defineProps<{ documentId: string; title: string; size?: string }>()
</script>
