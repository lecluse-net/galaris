import { defineAsyncComponent } from 'vue'

const DocumentEditor = defineAsyncComponent(() => import('@/app/document/components/DocumentEditor.vue'))
import type { WorkingDocumentEditorContribution } from '@/core/util'
const service = async () => (await import('./services/documentService')).documentService

export default {
  component: DocumentEditor,
  dialogComponent: defineAsyncComponent(() => import('@/app/document/components/DocumentDialog.vue')),
  iconComponent: defineAsyncComponent(() => import('@/app/document/components/DocumentIcon.vue')),
  thumbnailComponent: defineAsyncComponent(() => import('@/app/document/components/DocumentThumbnail.vue')),
  async resolve(id) {
    const detail = await (await service()).getManagedDocument(id)
    return { item: detail.item, agentId: detail.agent_id }
  },
  async search(query, limit, offset) {
    const page = await (await service()).browseDocumentLibrary({ query, limit, offset, include_keywords: false })
    return { items: page.entries.map(({ item }) => ({ id: item.id, title: item.title })), total: page.total }
  },
} satisfies WorkingDocumentEditorContribution
