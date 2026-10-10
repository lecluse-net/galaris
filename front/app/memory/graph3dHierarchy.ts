import type { MemoryGraphNode } from './types'

/** Display levels, never a change to the canonical classification or links. */
export function graphNodeLevel(node: MemoryGraphNode): number {
  if (node.entity_kind === 'topic' || node.entity_kind === 'contact'
    || node.entity_kind === 'directory' && /^[a-z][a-z0-9+.-]*:\/\/\/?$/i.test(node.resource_uri ?? '')) return 0
  if (node.entity_kind === 'folder' || node.entity_kind === 'directory') return 1
  return node.entity_kind === 'document' ? 2 : 3
}

export const GRAPH_DEPTH_STEP = 320
