import type { Component } from 'vue'
import { defineAsyncView } from './asyncView'

const providers = import.meta.glob<{ default: Component }>('../../resourceEmbeds.vue')
export const ResourceEmbed = defineAsyncView(async () => {
  const provider = Object.values(providers)[0]
  if (!provider) throw new Error('Resource embed provider unavailable')
  return (await provider()).default
})
export interface ResourceEmbedTarget { key: number; element: HTMLElement; uri: string; title: string }
