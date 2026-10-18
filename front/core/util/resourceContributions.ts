import type { Component } from 'vue'
import { defineAsyncView } from './asyncView'

const thumbnails = import.meta.glob<{ default: Component }>('../../resourceThumbnails.vue')
const references = import.meta.glob<{ default: Component }>('../../documentResourceReferences.vue')
async function provider(sources: Record<string, () => Promise<{ default: Component }>>): Promise<Component> {
  const load = Object.values(sources)[0]
  if (!load) throw new Error('Resource contribution unavailable')
  return (await load()).default
}
export const ResourceThumbnail = defineAsyncView(() => provider(thumbnails))
export const DocumentResourceReferences = defineAsyncView(() => provider(references))
