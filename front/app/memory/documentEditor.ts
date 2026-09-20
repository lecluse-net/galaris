import { defineAsyncComponent } from 'vue'

const DocumentEditor = defineAsyncComponent(() => import('./components/DocumentEditor.vue'))
import type { WorkingDocumentEditorContribution } from '@/core/util'
import { memoryService } from './services/memoryService'

export default {
  component: DocumentEditor,
  iconComponent: defineAsyncComponent(() => import('./components/DocumentIcon.vue')),
  thumbnailComponent: defineAsyncComponent(() => import('./components/DocumentThumbnail.vue')),
  async search(query, limit, offset) {
    const page = await memoryService.browseDocumentLibrary({ query, limit, offset })
    return { items: page.entries.map(({ item }) => ({ id: item.id, title: item.title })), total: page.total }
  },
} satisfies WorkingDocumentEditorContribution
