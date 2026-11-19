<template><DocumentEditor v-if="ready" ref="editor" :document-id="documentId" :agent-id="agentId" /></template>

<script lang="ts">
import { registerDrawingSample } from '../../plugins/sample/drawing'
registerDrawingSample()
</script>

<script setup lang="ts">
import { ref, useTemplateRef } from 'vue'
import { DocumentEditor } from '@/app/document'
import { documentService } from '@/app/document/services/documentService'
const { archive } = defineProps<{ documentId: string; agentId: number; archive?: boolean }>()
const ready = ref(!archive)
if (archive) void documentService.formats().then(() => { ready.value = true })
const editor = useTemplateRef<InstanceType<typeof DocumentEditor>>('editor')
defineExpose({ captureFocus: () => editor.value?.captureFocus() })
</script>
