import { ref } from 'vue'
import { topicService } from '../services/topicService'

export function useTopicRefs() {
  const titles = ref<Record<string, string>>({})

  async function resolveTopicRefs(ids: Array<string | null | undefined>): Promise<void> {
    const normalized = ids.filter((id): id is string => typeof id === 'string' && id.length > 0)
    const missing = [...new Set(normalized.filter(id => titles.value[id] === undefined))]
    if (!missing.length) return
    try {
      const refs = await topicService.refs(missing)
      titles.value = {
        ...titles.value,
        ...Object.fromEntries(refs.map(topic => [topic.id, topic.title])),
      }
    } catch {
      // Monitoring remains usable when compact Topic labels are not authorized.
    }
  }

  function topicTitle(id: string | null | undefined): string {
    return id ? titles.value[id] || '' : ''
  }

  return { titles, resolveTopicRefs, topicTitle }
}
