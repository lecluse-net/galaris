import type { RichContentContribution } from '@/core/util'
import { canonicalResourceLink } from '@/core/util/facade'

export default {
  // Keep specialized document/business contributions first. Any other canonical
  // reference opens the existing browser; provider access is checked there.
  fallback: true,
  search: async () => [],
  href: uri => canonicalResourceLink(uri) ? `/files?uri=${encodeURIComponent(uri)}` : null,
  canonical: value => canonicalResourceLink(value) ? value : null,
  canPreviewImage: canonicalResourceLink,
  async previewImage(uri, agentId, signal) {
    if (agentId === null) return null
    const { fileBrowserService } = await import('./services/fileBrowserService')
    return fileBrowserService.thumbnail(agentId, uri, signal)
  },
  async fullImage(uri, agentId, signal) {
    const { fileBrowserService } = await import('./services/fileBrowserService')
    const entry = await fileBrowserService.info(agentId, uri, signal)
    if (!/^image\/(png|jpeg|webp|gif)$/.test(entry.media_type) || entry.size == null || entry.size > 20_000_000) return null
    return fileBrowserService.content(agentId, uri, false, signal)
  },
} satisfies RichContentContribution
