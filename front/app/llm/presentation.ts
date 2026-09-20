import type { AIMessage, ExecutionResult } from '@/app/task/types'
import type { LLMCall, ReasoningEffort } from './types'


const CONTEXT_DISPLAY_KEYS = ['datetime', 'weekday', 'user_name', 'user_id'] as const

const REASONING_EFFORT_COLORS: Record<ReasoningEffort, string> = {
  none: 'grey-7',
  low: 'light-blue-7',
  medium: 'amber-8',
  high: 'deep-orange-7',
  xhigh: 'red-7',
  max: 'purple-8',
}

export function reasoningEffortColor(effort: ReasoningEffort): string {
  return REASONING_EFFORT_COLORS[effort]
}


// Mirror backend normalize_tool_name behavior. Prefixes may be stacked
// (for example mcp__galaris__galaris_...), so strip them until none remain.
const MCP_GALARIS_TOOL_PREFIXES = ['mcp_galaris_', 'mcp__galaris__', 'galaris_'] as const

export interface CallPresentationLabels {
  contextTitle: string
  contextKey: string
  contextValue: string
  agentName?: string
  userName?: string
}

const DEFAULT_CALL_PRESENTATION_LABELS: CallPresentationLabels = {
  contextTitle: 'Galaris message context',
  contextKey: 'Key',
  contextValue: 'Value',
}

function displayToolName(name: string): string {
  let result = name
  let stripped = true
  while (stripped) {
    stripped = false
    for (const prefix of MCP_GALARIS_TOOL_PREFIXES) {
      if (result.startsWith(prefix)) {
        result = result.slice(prefix.length)
        stripped = true
        break
      }
    }
  }
  return result
}


function formatRequestToolCall(tool: Record<string, any>): string {
  const fn = (tool.function || {}) as Record<string, any>
  const name = displayToolName(String(fn.name || tool.name || 'tool'))
  const args = fn.arguments ?? tool.arguments ?? ''
  const argsText = typeof args === 'string' ? args : JSON.stringify(args)
  return `🔧 \`${name}(${argsText})\``
}

function messageContentText(content: unknown): string {
  return typeof content === 'string'
    ? content
    : JSON.stringify(content ?? '', null, 2)
}

function imagePartUrl(part: Record<string, any>): string {
  const image = part.image_url ?? part.url
  if (typeof image === 'string') return image
  if (image && typeof image === 'object' && typeof image.url === 'string') return image.url

  const source = part.source
  if (
    source
    && typeof source === 'object'
    && typeof source.media_type === 'string'
    && typeof source.data === 'string'
  ) {
    return `data:${source.media_type};base64,${source.data}`
  }
  return ''
}

function visionMessageContent(content: unknown): string {
  if (!Array.isArray(content)) return messageContentText(content)

  return content
    .map((rawPart) => {
      if (!rawPart || typeof rawPart !== 'object') return messageContentText(rawPart)
      const part = rawPart as Record<string, any>
      const blocks: string[] = []
      const text = typeof part.text === 'string'
        ? part.text
        : (typeof part.content === 'string' ? part.content : '')
      if (text.trim()) blocks.push(text)

      const imageUrl = imagePartUrl(part)
      if (imageUrl) blocks.push(`![image](${imageUrl})`)
      return blocks.join('\n\n')
    })
    .filter(Boolean)
    .join('\n\n')
}

function markdownTableCell(value: unknown): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return String(text ?? '')
    .replace(/\r?\n/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/\|/g, '\\|')
    .trim()
}

function contextBlockTable(rawContext: string, labels: CallPresentationLabels): string {
  const raw = rawContext.trim()
  let rows: Array<[string, unknown]>
  try {
    const parsed = JSON.parse(raw) as unknown
    rows = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? Object.entries(parsed as Record<string, unknown>)
      : [['value', parsed]]
  } catch {
    rows = [['value', raw]]
  }

  const body = rows
    .filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '')
    .map(([key, value]) => `| \`${markdownTableCell(key)}\` | ${markdownTableCell(value)} |`)
    .join('\n')

  return [
    `### ${labels.contextTitle}`,
    '',
    `| ${labels.contextKey} | ${labels.contextValue} |`,
    '| --- | --- |',
    body || '| `value` | |',
  ].join('\n')
}

function leadingJsonObjectEnd(content: string): number | null {
  const start = content.search(/\S/)
  if (start < 0 || content[start] !== '{') return null

  let depth = 0
  let inString = false
  let escaped = false
  for (let i = start; i < content.length; i += 1) {
    const char = content[i]
    if (inString) {
      if (escaped) {
        escaped = false
      } else if (char === '\\') {
        escaped = true
      } else if (char === '"') {
        inString = false
      }
      continue
    }
    if (char === '"') {
      inString = true
    } else if (char === '{') {
      depth += 1
    } else if (char === '}') {
      depth -= 1
      if (depth === 0) return i + 1
    }
  }
  return null
}

function compactLeadingContextJson(content: string, labels: CallPresentationLabels): string {
  const end = leadingJsonObjectEnd(content)
  if (end === null) return content

  const candidate = content.slice(0, end)
  const rest = content.slice(end)
  if (!/^\s*\n\s*\n/.test(rest)) return content

  let parsed: unknown
  try {
    parsed = JSON.parse(candidate)
  } catch {
    return content
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return content

  const keys = Object.keys(parsed as Record<string, unknown>)
  const isContext = keys.length > 0 && keys.every(key => CONTEXT_DISPLAY_KEYS.includes(key as typeof CONTEXT_DISPLAY_KEYS[number]))
  if (!isContext) return content

  const body = rest.trimStart()
  return body
    ? `${contextBlockTable(candidate, labels)}\n\n${body}`
    : contextBlockTable(candidate, labels)
}

function formatPromptXmlTags(content: string): string {
  const parts = content.split(/(```[\s\S]*?```)/g)
  return parts.map(part => {
    if (part.startsWith('```')) return part
    return part.replace(/<\/?([a-zA-Z_][a-zA-Z0-9_-]*)>/g, (match: string, tagName: string) => {
      if (match.startsWith('</')) return ''
      const title = tagName
        .replace(/_/g, ' ')
        .replace(/-/g, ' ')
        .replace(/^\w/, (char: string) => char.toUpperCase())
      return `### ${title}`
    })
  }).join('')
}

function compactLastMessageContext(content: string, labels: CallPresentationLabels): string {
  const matches = [...content.matchAll(/<galaris_message_context>\s*([\s\S]*?)\s*<\/galaris_message_context>/g)]
  const last = matches[matches.length - 1]
  if (!last || last.index === undefined) return content

  return [
    content.slice(0, last.index),
    contextBlockTable(last[1] || '', labels),
    content.slice(last.index + last[0].length),
  ].join('')
}

interface ConversationSpeakerRecord {
  role: string
  name: string
}

function metadataSpeakerRecords(content: unknown): ConversationSpeakerRecord[] {
  if (typeof content !== 'string') return []
  const blocks = [...content.matchAll(
    /<conversation_history_metadata>\s*([\s\S]*?)\s*<\/conversation_history_metadata>/g,
  )]
  return blocks.flatMap((match) => {
    const body = match[1] || ''
    const start = body.indexOf('{')
    const end = body.lastIndexOf('}')
    if (start < 0 || end <= start) return []
    try {
      const parsed = JSON.parse(body.slice(start, end + 1)) as Record<string, unknown>
      const messages = Array.isArray(parsed.messages) ? parsed.messages : []
      return messages.flatMap((raw): ConversationSpeakerRecord[] => {
        if (!raw || typeof raw !== 'object') return []
        const record = raw as Record<string, unknown>
        const sender = record.sender && typeof record.sender === 'object'
          ? record.sender as Record<string, unknown>
          : null
        let name = String(
          record.speaker_name
          || sender?.display_name
          || sender?.external_id
          || '',
        ).trim()
        if (!name && typeof record.post_metadata === 'string') {
          const parts = record.post_metadata.split('|').map(part => part.trim()).filter(Boolean)
          const last = parts.at(-1)?.toLocaleLowerCase()
          name = last === 'human' || last === 'ai'
            ? String(parts.at(-2) || '')
            : String(parts.at(-1) || '')
        }
        return name ? [{ role: String(record.role || ''), name }] : []
      })
    } catch {
      return []
    }
  })
}

function conversationSpeakerNames(call: LLMCall): Map<number, string> {
  const names = new Map<number, string>()
  let pending: ConversationSpeakerRecord[] = []
  call.request_messages.forEach((message, index) => {
    if (message.role === 'system') {
      const records = metadataSpeakerRecords(message.content)
      if (records.length) pending = records
      return
    }
    if (!pending.length) return
    const role = String(message.role || '')
    const matchIndex = pending.findIndex(record => !record.role || record.role === role)
    const recordIndex = matchIndex >= 0 ? matchIndex : 0
    const [record] = pending.splice(recordIndex, 1)
    if (record?.name) names.set(index, record.name)
  })
  return names
}

function messageHeader(
  call: LLMCall,
  labels: CallPresentationLabels,
  message: Record<string, any>,
  speakerName: string | undefined,
): string {
  const role = String(message.role || 'message').toLowerCase()
  const raw = speakerName
    || (role === 'assistant' ? labels.agentName || call.agent_name : '')
    || (role === 'user' ? labels.userName : '')
    || role.replace(/^\w/, char => char.toUpperCase())
  return String(raw).replace(/\s+/g, ' ').trim()
}

// Render the client payload faithfully, including assistant tool_calls. Without them,
// tool-only assistant turns would appear empty. System messages have their own tab:
// prompt plus system prompt exactly reconstruct request_messages.
export function formatCallMessages(
  call: LLMCall,
  labels: CallPresentationLabels = DEFAULT_CALL_PRESENTATION_LABELS,
): string {
  const speakerNames = conversationSpeakerNames(call)
  const messages = call.request_messages
    .map((message, originalIndex) => ({ message, originalIndex }))
    .filter(({ message }) => message.role !== 'system')
  const contentText = call.call_type === 'vision'
    ? visionMessageContent
    : messageContentText
  const lastContextMessageIndex = messages.reduce((last, entry, index) => (
    messageContentText(entry.message.content).includes('<galaris_message_context>')
      ? index
      : last
  ), -1)

  return messages
    .map(({ message, originalIndex }, index) => {
      const speaker = messageHeader(
        call,
        labels,
        message,
        speakerNames.get(originalIndex),
      )
      const header = message.tool_call_id ? `## ${speaker} (${message.tool_call_id})` : `## ${speaker}`
      const parts: string[] = []
      const rawContent = index === lastContextMessageIndex
        ? compactLastMessageContext(contentText(message.content), labels)
        : contentText(message.content)
      const content = compactLeadingContextJson(rawContent, labels)
      if (content.trim()) parts.push(formatPromptXmlTags(content))
      for (const tool of (message.tool_calls || []) as Array<Record<string, any>>) {
        parts.push(formatRequestToolCall(tool))
      }
      return `${header}\n\n${parts.join('\n\n')}`
    })
    .join('\n\n---\n\n') || call.prompt
}

export function callExecutionResult(
  call: LLMCall,
  toolPending: string,
  labels: CallPresentationLabels = DEFAULT_CALL_PRESENTATION_LABELS,
): ExecutionResult {
  const messages: AIMessage[] = []
  if (call.reasoning) {
    messages.push({ type: 'tool', tool_name: 'thinking', content: call.reasoning })
  }
  for (const tool of call.tool_calls || []) {
    const result = tool.result == null
      ? toolPending
      : (typeof tool.result === 'string' ? tool.result : JSON.stringify(tool.result, null, 2))
    messages.push({
      type: 'tool',
      tool_name: displayToolName(tool.name || 'tool'),
      tool_arguments: tool.arguments || {},
      content: result,
    })
  }
  if (call.response_text) messages.push({ type: 'text', content: call.response_text })
  return {
    prompt: formatCallMessages(call, labels),
    system_prompt: call.system_prompt,
    messages,
    execution_time: call.duration,
    result: call.response_text,
    cost: call.cost,
    tools_used: (call.tool_calls || []).map(tool => displayToolName(tool.name)),
    success: call.status === 'completed',
  }
}

export function formatExecutionTime(time: number): string {
  if (time == null || isNaN(time)) return '—'
  if (time < 1) return `${Math.round(time * 1000)}ms`
  if (time < 60) return `${time.toFixed(2)}s`
  const minutes = Math.floor(time / 60)
  const seconds = (time % 60).toFixed(2)
  return `${minutes}m ${seconds}s`
}

export function formatCostShort(cost: number): string {
  if (cost == null || isNaN(cost)) return '$0.00'
  if (cost === 0) return '$0.00'

  // Convert to a string to inspect the decimal part.
  const costStr = cost.toString()

  // Use two decimal places for integers and short decimal values.
  const decimalPart = costStr.split('.')[1]
  if (!decimalPart || decimalPart.length <= 2) return `$${cost.toFixed(2)}`

  // Count leading zeros after the decimal point.
  const leadingZeros = decimalPart.match(/^0*/)?.[0].length || 0

  // Cap very small values at six decimal places.
  if (leadingZeros >= 5) return `$${cost.toFixed(6)}`

  // Otherwise preserve significant decimals, up to six places.
  const significantDigits = decimalPart.substring(leadingZeros)
  const totalDecimals = Math.min(leadingZeros + significantDigits.length, 6)

  return `$${cost.toFixed(totalDecimals)}`
}

export function formatBilledCost(cost: number): string {
  return formatApiCost(cost)
}

export function formatApiCost(cost: number): string {
  if (!Number.isFinite(cost)) return '0.00'
  const compact = cost.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')
  return compact.includes('.') ? compact : `${compact}.00`
}
