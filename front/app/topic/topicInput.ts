import type { TopicInput } from './types'

export function normalizeTopicInput(form: TopicInput): TopicInput {
  return {
    title: form.title.trim(),
    description: form.description.trim(),
    keywords: [...new Set(form.keywords.map(value => value.trim().slice(0, 80)).filter(Boolean))].slice(0, 20),
  }
}
