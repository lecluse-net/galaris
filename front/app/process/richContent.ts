import type { RichContentContribution } from '@/core/util'
import { processResourceTarget, processReferenceHtml } from './contracts'
import { processResourceService } from './services/processResourceService'

export default {
  schemes: ['process'],
  search: query => processResourceService.search(query),
  target: processResourceTarget,
  async card(uri, agentId) {
    const preview = await processResourceService.preview(uri, agentId)
    return processReferenceHtml(preview.uri, preview.title, true)
  },
  href(uri) {
    const target = processResourceTarget(uri)
    if (!target) return null
    return target.kind === 'process' ? `/process/internal/${encodeURIComponent(target.id)}` : `/process/internal/run/${target.id}`
  },
} satisfies RichContentContribution
