<template>
  <component :is="workingDocumentThumbnail" v-if="workingDocumentThumbnail" v-bind="props" />
  <q-icon v-else name="description" size="28px" aria-hidden="true" />
</template>
<script setup lang="ts">
import { workingDocumentThumbnail } from '../workingDocumentEditor'
const props = defineProps<{
  documentId: string
  revision?: number | null
  updatedAt?: string | null
  agentId?: number | null
  fill?: boolean
}>()
</script>
