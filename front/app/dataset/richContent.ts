import type { RichContentContribution } from '@/core/util'
import { datasetService } from './services/datasetService'

export default {
  schemes: ['data'],
  async search(query) {
    const page = await datasetService.list(1, 50, query)
    return page.items.map(item => ({ uri: item.uri, title: item.title, context: '' }))
  },
  href(uri) {
    const match = /^data:\/\/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/.exec(uri)
    return match ? `/dataset/${match[1]}` : null
  },
  target(uri, title = '', agentId = null) {
    const match = /^data:\/\/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/.exec(uri)
    return match ? { kind: 'dataset', id: match[1]!, title, agentId } : null
  },
} satisfies RichContentContribution
