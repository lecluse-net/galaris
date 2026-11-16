import type { RichContentContribution } from '@/core/util'
import { canonicalResourceLink } from '@/core/util/facade'

export default {
  // Keep specialized document/business contributions first. Any other canonical
  // reference opens the existing browser; provider access is checked there.
  fallback: true,
  search: async () => [],
  href: uri => canonicalResourceLink(uri) ? `/files?uri=${encodeURIComponent(uri)}` : null,
  canonical: value => canonicalResourceLink(value) ? value : null,
} satisfies RichContentContribution
