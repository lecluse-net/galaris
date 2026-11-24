import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js'
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { InitializeRequestSchema, LATEST_PROTOCOL_VERSION, ReadResourceRequestSchema, RequestSchema, ResultSchema, SUPPORTED_PROTOCOL_VERSIONS } from '@modelcontextprotocol/sdk/types.js'
import type { LocalMcp } from './mcpDiscovery.ts'

export interface RelayDelivery { request: string; session: string; message: unknown }
export type RelayReply = { result: Record<string, unknown> } | { missing: true } | { error: { code: number; message: string } }
const methodNotFound = { error: { code: -32601, message: 'MCP method unavailable through desktop relay' } }
const localFailure = { error: { code: -32000, message: 'Local MCP request failed' } }
const fileReadDenied = { error: { code: -32003, message: 'Direct local file reads are disabled through the desktop relay' } }
const methods = new Set(['ping', 'tools/list', 'tools/call', 'resources/list', 'resources/templates/list',
  'resources/read', 'prompts/list', 'prompts/get'])
const idleMs = 120_000
const sessionLimit = 16

type AccessRejection = 401 | 403

function transportFor(options: LocalMcp['options'], sessionSignal: AbortSignal,
  onAccessRejected?: (status: AccessRejection) => void) {
  if (options.transport === 'stdio') {
    return new StdioClientTransport({ command: options.command, args: options.args,
      cwd: options.cwd, env: options.env, stderr: 'ignore' })
  }
  const fetchLocal: typeof fetch = async (input, init) => {
    const target = input instanceof Request ? input.url : input
    if (new URL(target).origin !== options.url.origin) throw new Error('Local MCP changed origin')
    const deadline = init?.method === 'DELETE' ? AbortSignal.timeout(1000) : sessionSignal
    const signal = init?.signal ? AbortSignal.any([deadline, init.signal]) : deadline
    const response = await fetch(input, { ...init, redirect: 'error', signal })
    if (init?.method !== 'DELETE' && (response.status === 401 || response.status === 403)) {
      onAccessRejected?.(response.status)
    }
    return response
  }
  const configuration = { requestInit: { headers: options.headers }, fetch: fetchLocal }
  return options.transport === 'sse'
    ? new SSEClientTransport(options.url, configuration)
    : new StreamableHTTPClientTransport(options.url, configuration)
}

export class LocalMcpSessions {
  private readonly clients = new Map<string, {
    client: Client; transport: ReturnType<typeof transportFor>; timeout?: NodeJS.Timeout
  }>()
  private readonly options: LocalMcp['options']
  private readonly signal: AbortSignal
  private readonly onAccessRejected?: (status: AccessRejection) => void

  constructor(options: LocalMcp['options'], signal: AbortSignal,
    onAccessRejected?: (status: AccessRejection) => void) {
    this.options = options
    this.signal = signal
    this.onAccessRejected = onAccessRejected
    signal.addEventListener('abort', () => {
      for (const key of this.clients.keys()) void this.close(key)
    }, { once: true })
  }

  private async close(key: string): Promise<void> {
    const session = this.clients.get(key)
    if (!session) return
    this.clients.delete(key)
    clearTimeout(session.timeout)
    if (session.transport instanceof StreamableHTTPClientTransport) {
      await session.transport.terminateSession().catch(() => {})
    }
    await session.client.close().catch(() => {})
  }

  private refresh(key: string): void {
    const session = this.clients.get(key)
    if (!session) return
    clearTimeout(session.timeout)
    session.timeout = setTimeout(() => { void this.close(key) }, idleMs)
    session.timeout.unref()
  }

  async handle(delivery: RelayDelivery): Promise<RelayReply> {
    const key = delivery.session
    if (delivery.message === null) {
      await this.close(key)
      return { result: {} }
    }
    const request = RequestSchema.safeParse(delivery.message)
    if (!request.success || this.signal.aborted) return localFailure
    const method = request.data.method
    if (method === 'initialize') {
      const init = InitializeRequestSchema.safeParse(delivery.message)
      if (!init.success || this.clients.has(key) || this.clients.size >= sessionLimit) return localFailure
      const { protocolVersion, capabilities } = init.data.params
      const client = new Client({ name: 'Galaris Desktop', version: '1.0.0' }, {
        capabilities: { extensions: capabilities.extensions }
      })
      try {
        const transport = transportFor(this.options, this.signal, this.onAccessRejected)
        this.clients.set(key, { client, transport })
        await client.connect(transport, { signal: this.signal, timeout: 4_000 })
        const server = client.getServerCapabilities()
        const version = client.getServerVersion()
        if (this.signal.aborted || this.clients.get(key)?.client !== client || !version) throw new Error('MCP session closed')
        this.refresh(key)
        return { result: {
          protocolVersion: SUPPORTED_PROTOCOL_VERSIONS.includes(protocolVersion) ? protocolVersion : LATEST_PROTOCOL_VERSION,
          serverInfo: version,
          instructions: client.getInstructions(),
          capabilities: { tools: server?.tools && {}, resources: server?.resources && {}, prompts: server?.prompts && {} }
        } }
      } catch {
        await this.close(key)
        return localFailure
      }
    }
    const session = this.clients.get(key)
    if (!session) return { missing: true }
    if (!methods.has(method)) return methodNotFound
    if (method === 'resources/read') {
      const read = ReadResourceRequestSchema.safeParse(request.data)
      if (!read.success) return localFailure
      if (/^file:/i.test(read.data.params.uri.trim())) return fileReadDenied
    }
    this.refresh(key)
    try {
      const result = await session.client.request(request.data, ResultSchema, { signal: this.signal, timeout: 20_000 })
      return { result }
    } catch {
      return localFailure
    }
  }
}

/** Check for an explicit access rejection. A local server may be started after sharing. */
export async function checkLocalMcpAuthentication(options: LocalMcp['options']): Promise<AccessRejection | undefined> {
  if (options.transport === 'stdio') return
  let rejection: AccessRejection | undefined
  const sessions = new LocalMcpSessions(options, AbortSignal.timeout(5000), status => { rejection ??= status })
  const delivery = { request: 'probe', session: 'probe' }
  try {
    const reply = await sessions.handle({ ...delivery, message: { method: 'initialize', params: {
      protocolVersion: LATEST_PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: 'Galaris Desktop', version: '1.0.0' }
    } } })
    if ('error' in reply) return rejection
  } finally {
    await sessions.handle({ ...delivery, message: null })
  }
}
