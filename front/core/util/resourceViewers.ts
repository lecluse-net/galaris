/** File readers are independent of document ownership and storage providers. */
import { markRaw, shallowReactive } from 'vue'
import type { Component } from 'vue'
export interface ResourceViewerSource {
  key: string
  uri?: string
  name: string
  mediaType: string
  size: number
  load: (signal: AbortSignal) => Promise<Blob>
}
export interface ResourceViewerContribution {
  code: string
  version: number
  provider: string
  priority?: number
  icon: string
  accepts: (mediaType: string, name: string) => boolean
  component: Component
}
const viewers = shallowReactive<ResourceViewerContribution[]>([])
export function registerResourceViewer(viewer: ResourceViewerContribution): void {
  if (!viewer.code || !viewer.provider || !Number.isSafeInteger(viewer.version) || viewer.version < 1
    || viewers.some(current => current.code === viewer.code)) throw new Error('Invalid or duplicate resource viewer')
  viewers.push({ ...viewer, component: markRaw(viewer.component) })
  viewers.sort((left, right) => (right.priority ?? 0) - (left.priority ?? 0) || left.code.localeCompare(right.code))
}
export function findResourceViewer(mediaType: string, name: string): ResourceViewerContribution | undefined {
  return viewers.find(viewer => viewer.accepts(mediaType.split(';', 1)[0]?.trim().toLowerCase() ?? '', name))
}
