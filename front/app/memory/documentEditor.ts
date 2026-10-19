import { defineAsyncComponent } from 'vue'

const DocumentEditor = defineAsyncComponent(() => import('./components/DocumentEditor.vue'))
import type { WorkingDocumentEditorContribution } from '@/core/util'
import { memoryService } from './services/memoryService'

export default {
  component: DocumentEditor,
  dialogComponent: defineAsyncComponent(() => import('./components/DocumentDialog.vue')),
  iconComponent: defineAsyncComponent(() => import('./components/DocumentIcon.vue')),
  thumbnailComponent: defineAsyncComponent(() => import('./components/DocumentThumbnail.vue')),
  async resolve(id) {
    const detail = await memoryService.getManagedDocument(id)
    return { item: detail.item, agentId: detail.agent_id }
  },
  async search(query, limit, offset) {
    const page = await memoryService.browseDocumentLibrary({ query, limit, offset, include_keywords: false })
    return { items: page.entries.map(({ item }) => ({ id: item.id, title: item.title })), total: page.total }
  },
} satisfies WorkingDocumentEditorContribution
