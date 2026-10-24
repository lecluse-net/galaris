<template>
  <component :is="conversationPanel" v-if="conversationPanel" :document-id="documentId" :before-send="beforeSend" :capture-document-focus="captureDocumentFocus" :visible="visible"
    @close="emit('close')" @open-document="emit('open-document', $event)" />
</template>

<script setup lang="ts">
import { conversationPanel } from '../conversationPanel'
import type { DocumentFocus } from '../documentFocus'
defineProps<{ documentId: string | null; beforeSend: () => Promise<boolean>; captureDocumentFocus?: () => DocumentFocus | null; visible: boolean }>()
const emit = defineEmits<{ close: []; 'open-document': [id: string] }>()
</script>
