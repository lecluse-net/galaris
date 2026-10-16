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
interface ResourceDetailProvider {
  default: Component
  preload?: (kind: string) => Promise<void>
}
const providers = import.meta.glob<ResourceDetailProvider>('../../resourceDetails.vue')
async function loadProvider(): Promise<ResourceDetailProvider> {
  const provider = Object.values(providers)[0]
  if (!provider) throw new Error('Resource details provider unavailable')
  return await provider()
}
export const ResourceDetailDialog = defineAsyncView(async () => (await loadProvider()).default)

/** Prepare view code only; resource data and authorization stay with the opened view. */
export async function preloadResourceDetail(kind: string): Promise<void> {
  const provider = await loadProvider()
  await provider.preload?.(kind)
}
