<template><ResourceAttachments resource-id="synthetic" :attachments="attachments" :resource-source="source" /></template>
<script setup lang="ts">
import { ResourceAttachments, registerResourceViewer, findResourceViewer, type AttachmentSource } from '@/core/util'
import SyntheticResourceViewer from './SyntheticResourceViewer.vue'
if (!findResourceViewer('application/x-example-note', 'synthetic.note')) registerResourceViewer({
  code: 'example.note', version: 1, provider: 'example', icon: 'account_tree',
  accepts: mime => mime === 'application/x-example-note', component: SyntheticResourceViewer,
})
const attachments = [{ id: 'synthetic', name: 'synthetic.note', media_type: 'application/x-example-note', size_bytes: 20 }]
const source: AttachmentSource = { content: async (_attachment, _preview, signal) => (await fetch('/api/synthetic-viewer/source', { signal })).blob() }
</script>
