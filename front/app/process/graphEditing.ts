import { emptyGraph, type BpmnGraph, type BpmnNode, type NodeKind } from './services/nativeProcessService'

export const activityKinds: NodeKind[] = ['task', 'human_task', 'if', 'parallel', 'for', 'while', 'call', 'tool_call', 'rest', 'code', 'end']
export const nodeIcons: Record<NodeKind, string> = { start: 'play_arrow', end: 'stop', task: 'smart_toy', human_task: 'person',
  if: 'alt_route', parallel: 'call_split', for: 'repeat', while: 'loop', call: 'account_tree', tool_call: 'build', rest: 'http', code: 'code', program: 'code' }
const identity = (prefix: string): string => prefix + '_' + crypto.randomUUID().replaceAll('-', '').slice(0, 12)
export const defaultDecisionCode = '# Example: return variable_2 != "pas mon projet"\nreturn True'
export const defaultTaskCode = '# Example: return {"variable_1": variable_1 + 1}\nreturn {}'

export function processingMode(node: BpmnNode, graph: BpmnGraph): 'ai' | 'code' | 'human' {
  const assigned = graph.actors?.find(actor => actor.id === node.config.actor)
  if (assigned?.kind === 'human' || node.kind === 'human_task') return 'human'
  return node.kind === 'code' || node.kind === 'if' && node.config.mode === 'code' ? 'code' : 'ai'
}

export function assignActivityActor(node: BpmnNode, key: string, graph: BpmnGraph): BpmnNode {
  const human = graph.actors?.find(actor => actor.id === key)?.kind === 'human'
  const config = { ...node.config, actor: key || null }
  if (node.kind === 'if' && graph.schema_version === 'galaris.bpmn/v2') return { ...node, config: { ...config, mode: human ? 'human' : node.config.mode === 'code' ? 'code' : 'ai' } }
  if (graph.schema_version === 'galaris.bpmn/v2' && ['task', 'human_task', 'code'].includes(node.kind))
    return { ...node, kind: human ? 'human_task' : node.kind === 'code' ? 'code' : 'task', config: { prompt: '', ...config } }
  return { ...node, config }
}

export function createActivity(kind: NodeKind, graph: BpmnGraph, actorKey?: string): BpmnNode {
  const inherited = graph.actors?.find(actor => actor.id === actorKey)
  if (graph.schema_version === 'galaris.bpmn/v2' && kind === 'task' && inherited?.kind === 'human') kind = 'human_task'
  const actor = graph.actors?.find(actor => actor.id === actorKey && (kind === 'if' || actor.kind === (kind === 'human_task' ? 'human' : 'agent')))
    ?? graph.actors?.find(actor => actor.kind === (kind === 'human_task' ? 'human' : 'agent'))
  const id = identity(kind)
  const body = kind === 'for' || kind === 'while' ? emptyGraph() : null
  if (body) {
    body.schema_version = graph.schema_version
    if (graph.schema_version === 'galaris.bpmn/v1') { delete body.inputs; delete body.outputs }
    body.nodes = body.nodes.map(node => ({ ...node, id: id + '_' + node.id }))
    body.flows = body.flows.map(flow => ({ ...flow, id: id + '_' + flow.id, source: id + '_' + flow.source, target: id + '_' + flow.target }))
    body.actors = (graph.actors ?? []).map(actor => ({ ...actor }))
  }

  const config: Record<string, unknown> = kind === 'task' || kind === 'human_task' ? { prompt: '' } : kind === 'for' ? { items: 'input.items' } : kind === 'while' ? { condition: 'false' } : {}
  if (kind === 'if' && graph.schema_version === 'galaris.bpmn/v2') Object.assign(config, { mode: actor?.kind === 'human' ? 'human' : 'ai', prompt: '', code: defaultDecisionCode })
  if (kind === 'code') Object.assign(config, { code: defaultTaskCode, dataset_code: true })
  if (actor && ['task', 'human_task', 'code', 'if'].includes(kind)) config.actor = actor.id
  const declarations = graph.schema_version === 'galaris.bpmn/v2' && ['task', 'human_task', 'tool_call', 'rest', 'code', 'program', 'call'].includes(kind) ? { inputs: [], outputs: [] } : {}
  return { id, kind, title: '', config, body, x: 0, y: 0, ...declarations }
}

export function insertActivity(graph: BpmnGraph, anchor: string, side: 'input' | 'output', kind: NodeKind, branch = false, outcome?: boolean): { graph: BpmnGraph; id: string } {
  const parent = graph.nodes.find(node => node.id === anchor)!
  const node = createActivity(kind, graph, String(parent.config.actor ?? ''))
  const adjacent = graph.flows.filter(flow => side === 'output' ? flow.source === anchor && (outcome === undefined || (flow.condition !== null) === outcome) : flow.target === anchor)
  if (side === 'input' && !branch && adjacent.length > 1) {
    return { graph: { ...graph, nodes: [...graph.nodes, node], flows: [...graph.flows.map(flow => flow.target === anchor ? { ...flow, target: node.id } : flow),
      { id: identity('flow'), source: node.id, target: anchor, condition: null },
      ...(node.kind === 'if' && node.config.mode ? [{ id: identity('flow'), source: node.id, target: anchor, condition: 'decision' }] : [])] }, id: node.id }
  }
  const splice = !branch && adjacent.length === 1 && kind !== 'end' ? adjacent[0] : undefined
  const flows = graph.flows.map(flow => flow.id === splice?.id ? { ...flow, target: node.id } : flow)
  flows.push({ id: identity('flow'), source: splice ? node.id : side === 'output' ? anchor : node.id,
    target: splice ? splice.target : side === 'output' ? node.id : anchor, condition: !splice && side === 'output' && outcome === true ? 'decision' : null })
  if (node.kind === 'if' && node.config.mode && splice) flows.push({ id: identity('flow'), source: node.id, target: splice.target, condition: 'decision' })
  return { graph: { ...graph, nodes: [...graph.nodes, node], flows }, id: node.id }
}

export function canConnectActivities(graph: BpmnGraph, source: string, target: string, outcome?: boolean): boolean {
  const from = graph.nodes.find(node => node.id === source), to = graph.nodes.find(node => node.id === target)
  if (!from || !to || source === target || from.kind === 'end' || to.kind === 'start') return false
  if (outcome !== undefined && from.kind !== 'if') return false
  if (from.kind === 'if' && from.config.mode && outcome === undefined) return false
  if (graph.flows.some(flow => flow.source === source && flow.target === target)) return true
  const visited = new Set<string>(), pending = [target]
  while (pending.length) {
    const id = pending.pop()!
    if (id === source) return false
    if (visited.has(id)) continue
    visited.add(id)
    pending.push(...graph.flows.filter(flow => flow.source === id).map(flow => flow.target))
  }
  return true
}

export function connectActivities(graph: BpmnGraph, source: string, target: string, outcome?: boolean): BpmnGraph {
  if (!canConnectActivities(graph, source, target, outcome)) return graph
  if (outcome !== undefined) {
    const existing = graph.flows.find(flow => flow.source === source && (flow.condition !== null) === outcome)
    if (existing) return existing.target === target ? graph : { ...graph, flows: graph.flows.map(flow => flow.id === existing.id ? { ...flow, target } : flow) }
  } else if (graph.flows.some(flow => flow.source === source && flow.target === target)) return graph
  return { ...graph, flows: [...graph.flows, { id: identity('flow'), source, target, condition: outcome === true ? 'decision' : null }] }
}

export const laneHeaderWidth = 240
export const nodeStartX = laneHeaderWidth + 52

export function graphLayout(graph: BpmnGraph): { positions: Record<string, { x: number; y: number }>; lanes: string[]; laneHeight: number } {
  const lanes = ['', ...(graph.actors ?? []).map(actor => actor.id)]
  const depths = new Map<string, number>()
  // Bounded relaxation also makes malformed, disconnected drafts editable.
  const start = graph.nodes.find(node => node.kind === 'start')
  if (start) depths.set(start.id, 0)
  for (let pass = 0; pass < graph.nodes.length; pass++) {
    let changed = false
    for (const flow of graph.flows) {
      const depth = depths.get(flow.source)
      if (depth !== undefined && flow.target !== start?.id && (depths.get(flow.target) ?? -1) < depth + 1) {
        depths.set(flow.target, Math.min(graph.nodes.length, depth + 1)); changed = true
      }
    }
    if (!changed) break
  }
  const buckets = new Map<string, number>()
  const slots = graph.nodes.map((node, index) => {
    const lane = Math.max(0, lanes.indexOf(String(node.config.actor ?? '')))
    const depth = depths.get(node.id) ?? index
    const key = lane + ':' + depth
    const slot = buckets.get(key) ?? 0; buckets.set(key, slot + 1)
    return { node, lane, depth, slot, key }
  })
  let laneHeight = Math.max(168, ...Array.from(buckets.values(), count => count * 112 + 56))
  if (!graph.actors?.length) {
    laneHeight = Math.max(laneHeight, ...slots.map(({ node, slot }) =>
      (node.y > 0 ? node.y : 48 + slot * 112) + (['start', 'end', 'if', 'parallel'].includes(node.kind) ? 116 : 88) + 4))
  }
  return { lanes, laneHeight, positions: Object.fromEntries(slots.map(({ node, lane, depth, slot, key }) => [node.id,
    { x: nodeStartX + depth * 280, y: lane * laneHeight + (laneHeight - (buckets.get(key) ?? 1) * 112) / 2 + slot * 112 + 12 }])) }
}

export function persistLayout(graph: BpmnGraph): BpmnGraph {
  const layout = graphLayout(graph), saved = graph.nodes.filter(node => node.x > 0)
  const offset = saved.length ? Math.max(0, nodeStartX - Math.min(...saved.map(node => node.x))) : 0
  return { ...graph, nodes: graph.nodes.map(node => ({ ...node,
    x: node.x > 0 ? node.x + offset : layout.positions[node.id]!.x,
    y: graph.actors?.length || node.y <= 0 ? layout.positions[node.id]!.y : node.y,
    body: node.body ? persistLayout(node.body) : null })) }
}
