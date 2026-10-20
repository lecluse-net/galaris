import { createSessionCatalogueCache, invalidateSessionReads, onSessionReadInvalidation } from '@/core/util/facade'

// Local directory mutations invalidate all resource-specific owner catalogues.
onSessionReadInvalidation('agent-selection', () => invalidateSessionReads('owner-options'))

/** Each domain retains its authorization scope and returns independent editable copies. */
export function createOwnerOptionsCache<T>() {
  return createSessionCatalogueCache<T>('owner-options', 300_000)
}
