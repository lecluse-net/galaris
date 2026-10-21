import type { Component } from 'vue'
import { defineAsyncView } from './asyncView'

type Assignment = { topic_id: string; lock_version: number }
interface ResourceTopicsProvider {
  default: Component
  reassignResourceTopic: (kind: 'document' | 'dataset', id: string, topicId: string,
    expectedTopicId: string | null, expectedLockVersion: number) => Promise<Assignment>
}

// Business composition stays beside resourceDetails.vue, outside core and domain graphs.
const providers = import.meta.glob<ResourceTopicsProvider>('../../resourceTopics.vue')
async function loadProvider(): Promise<ResourceTopicsProvider> {
  const provider = Object.values(providers)[0]
  if (!provider) throw new Error('Resource topic provider unavailable')
  return await provider()
}

export const ResourceTopicBadge = defineAsyncView(async () => (await loadProvider()).default)
export async function reassignResourceTopic(...args: Parameters<ResourceTopicsProvider['reassignResourceTopic']>): Promise<Assignment> {
  return await (await loadProvider()).reassignResourceTopic(...args)
}
