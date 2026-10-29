import type { RichContentContribution } from '@/core/util'
import { datasetResourceId } from './resource'

const reader = () => import('./referenceReader')

export default {
  schemes: ['data'],
  canonical(value) { const id = datasetResourceId(value); return id ? `data://${id}` : null },
  async search(query) {
    return (await reader()).search(query)
  },
  href(uri) {
    const id = datasetResourceId(uri)
    return id ? `/documents?document_id=${id}` : null
  },
  target(uri, title = '', agentId = null) {
    const id = datasetResourceId(uri)
    return id ? { kind: 'dataset', id, title, agentId } : null
  },
  async title(uri) {
    return (await reader()).title(uri)
  },
  async card(uri) {
    return (await reader()).card(uri)
  },
} satisfies RichContentContribution
