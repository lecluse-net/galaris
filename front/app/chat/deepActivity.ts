import type { DeepEvent } from './types'

export interface DeepActivityBlock {
  id: string
  parent: string | null
  name: string
  state: string
  output: string
  details: string
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function projectDeepActivity(events: readonly DeepEvent[]) {
  const blocks = new Map<string, DeepActivityBlock>()
  const tools = new Set<string>()
  const text: string[] = []
  let pendingText = ''
  let fenced = false
  let trailingLine = ''
  for (const event of events) {
    const payload = event.payload
    const content = stringValue(payload.content)
    if (event.kind === 'text') {
      const lines = (trailingLine + content).split('\n')
      trailingLine = lines.pop() ?? ''
      for (const line of lines) {
        if (/^\s*```/.test(line)) fenced = !fenced
        pendingText += line + '\n'
        if (!fenced && !line && pendingText.length >= 4000) {
          text.push(pendingText)
          pendingText = ''
        }
      }
      continue
    }
    if (event.kind !== 'activity') continue
    const activityId = stringValue(payload.activity_ref) || stringValue(payload.tool_call_external_id)
      || stringValue(payload.stream_id) || String(event.sequence)
    const parent = stringValue(payload.parent_activity_ref) || null
    const current = blocks.get(activityId)
    const name = current?.name || stringValue(payload.tool_name)
    if (name) {
      tools.delete(name)
      tools.add(name)
    }
    const state = stringValue(payload.activity_state) || (payload.success === false ? 'failed' : 'completed')
    const output = payload.tool_result
    const body = content || (output ? JSON.stringify(output, null, 2) : '')
    const append = payload.activity_state === 'running' && Boolean(current?.output) && Boolean(content)
    blocks.set(activityId, {
      id: activityId,
      parent: parent === activityId ? null : (parent ?? current?.parent ?? null),
      name,
      state,
      output: append ? current!.output + content : (body || current?.output || ''),
      details: output ? JSON.stringify(output, null, 2) : (current?.details ?? ''),
    })
  }
  if (pendingText || trailingLine) text.push(pendingText + trailingLine)
  const roots: DeepActivityBlock[] = []
  const children: Record<string, DeepActivityBlock[]> = Object.create(null)
  for (const block of blocks.values()) {
    let parent = block.parent
    const visited = new Set([block.id])
    while (parent && !visited.has(parent)) {
      visited.add(parent)
      parent = blocks.get(parent)?.parent ?? null
    }
    if (!parent && block.parent && blocks.has(block.parent)) (children[block.parent] ??= []).push(block)
    else roots.push(block)
  }
  return { roots, children, text, tools: [...tools] }
}
