<template><DocumentEditor :document-id="documentId" :agent-id="agentId" /></template>
<script setup lang="ts">
import { registerDocumentFormat, findDocumentFormat } from '@/app/document'
import DocumentEditor from '@/app/document/components/DocumentEditor.vue'
import SyntheticEditor from './SyntheticDocumentFormatEditor.vue'
import SyntheticBinaryEditor from './SyntheticBinaryFormatEditor.vue'
defineProps<{ documentId: string; agentId: number }>()
if (!findDocumentFormat('example.note')) registerDocumentFormat({
  code: 'example.note', version: 1, provider: 'example', label: 'documents.documentFormat', icon: 'account_tree',
  editor: SyntheticEditor, validateDraft: source => source.startsWith('note:'),
  snapshot: async source => `<pre>${source.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')}</pre>`,
})
if (!findDocumentFormat('example.binary')) registerDocumentFormat({
  code: 'example.binary', version: 1, provider: 'example', label: 'documents.documentFormat', icon: 'insert_drive_file',
  editor: SyntheticBinaryEditor, storageKind: 'file', validateDraft: () => true,
  snapshot: async (_text, _title, signal, _images, _rendered, source) => {
    if (!source?.readonly) throw new Error('A snapshot requires a read-only source')
    const content = await (await source.load(signal)).text()
    return `<pre>${content.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')}</pre>`
  },
})
</script>
