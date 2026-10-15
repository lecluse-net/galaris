import type { Component } from 'vue'
import { defineAsyncView } from './asyncView'

export interface ResourceDetailTarget {
  kind: string
  id: string
  title: string
  agentId?: number | null
}

// Application composition stays outside core and domain dependency graphs.
// The same entry point is available in the application and component harness.
const providers = import.meta.glob<{ default: Component }>('../../resourceDetails.vue')
export const ResourceDetailDialog = defineAsyncView(async () => {
  const provider = Object.values(providers)[0]
  if (!provider) throw new Error('Resource details provider unavailable')
  return (await provider()).default
})
