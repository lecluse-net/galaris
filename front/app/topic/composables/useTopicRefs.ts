import { onScopeDispose, ref } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { onSessionReadInvalidation } from '@/core/util/facade'
import { topicService } from '../services/topicService'

export function useTopicRefs() {
  const titles = ref<Record<string, string>>({})
  const observed = new Set<string>()
  let epoch = 0, disposed = false, session = sessionGeneration()

  async function resolveTopicRefs(ids: Array<string | null | undefined>): Promise<void> {
    if (disposed) return
    const normalized = [...new Set(ids.filter((id): id is string => typeof id === 'string' && id.length > 0))]
    for (const id of normalized) { observed.delete(id); observed.add(id) }
    while (observed.size > 1024) observed.delete(observed.values().next().value!)
    if (!normalized.length) return
    const request = epoch, generation = sessionGeneration()
    try {
      const refs = await topicService.refs(normalized)
      if (disposed || request !== epoch || generation !== sessionGeneration()) return
      titles.value = {
        // A refreshed catalogue may omit deleted or newly unauthorized topics.
        ...Object.fromEntries(Object.entries(titles.value).filter(([id]) => !normalized.includes(id))),
        ...Object.fromEntries(refs.map(topic => [topic.id, topic.title])),
      }
      titles.value = Object.fromEntries(Object.entries(titles.value).filter(([id]) => observed.has(id)))
    } catch {
      // Monitoring remains usable when compact Topic labels are not authorized.
    }
  }

  function invalidate(): void {
    epoch++
    titles.value = {}
    void resolveTopicRefs([...observed])
  }
  const unsubscribe = onSessionReadInvalidation('topic-references', invalidate)
  function sessionChanged(): void {
    const next = sessionGeneration()
    if (next === session) return
    session = next; epoch++; observed.clear(); titles.value = {}
  }
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged)
  window.addEventListener('storage', sessionChanged)
  onScopeDispose(() => {
    disposed = true; epoch++
    unsubscribe()
    window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged)
    window.removeEventListener('storage', sessionChanged)
  })

  function topicTitle(id: string | null | undefined): string {
    return id ? titles.value[id] || '' : ''
  }

  return { titles, resolveTopicRefs, topicTitle }
}
