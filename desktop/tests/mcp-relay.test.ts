import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import test from 'node:test'
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js'
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js'
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { parseMcpFile } from '../src/mcpDiscovery.ts'
import { checkLocalMcpAuthentication, LocalMcpSessions } from '../src/mcpSession.ts'

for (const [transport, protectedEndpoint] of [
  ['http', false], ['http', true], ['sse', false], ['sse', true],
] as const) {
  test(`relays a local ${transport} MCP ${protectedEndpoint ? 'with' : 'without'} a local token`, async () => {
    const token = 'Bearer synthetic-desktop-token'
    const local = new Server({ name: 'Synthetic inventory', version: '1' }, { capabilities: { tools: {} } })
    local.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [{ name: 'inventory', inputSchema: { type: 'object' } }]
    }))
    local.setRequestHandler(CallToolRequestSchema, async () => ({
      content: [{ type: 'text', text: 'Three synthetic items' }]
    }))
    let legacy: SSEServerTransport | undefined
    let deletedSession = false
    const http = new StreamableHTTPServerTransport({ sessionIdGenerator: () => 'synthetic-session', enableJsonResponse: true })
    if (transport === 'http') await local.connect(http)
    const endpoint = createServer((request, response) => {
      if (protectedEndpoint && request.headers.authorization !== token) {
        response.writeHead(request.headers.authorization ? 403 : 401).end()
        return
      }
      const serve = async () => {
        if (transport === 'http') {
          if (request.method === 'DELETE') deletedSession = true
          return http.handleRequest(request, response)
        }
        if (request.url === '/sse') {
          legacy = new SSEServerTransport('/messages', response)
          await local.connect(legacy)
        } else if (legacy && request.url?.startsWith('/messages?')) await legacy.handlePostMessage(request, response)
        else response.writeHead(404).end()
      }
      void serve().catch(() => { response.destroy() })
    })
    await new Promise<void>(resolve => endpoint.listen(0, '127.0.0.1', resolve))
    const address = endpoint.address()
    assert.ok(address && typeof address !== 'string')
    const abort = new AbortController()
    const url = `http://127.0.0.1:${address.port}/${transport}`
    const [entry] = parseMcpFile(JSON.stringify({ mcpServers: { inventory: {
      url, type: transport, headers: protectedEndpoint ? { Authorization: token } : {},
    } } }), 'synthetic.json', 'Synthetic local configuration')
    assert.ok(entry)
    const relay = new LocalMcpSessions(entry.options, abort.signal)
    const send = (message: unknown) => relay.handle({ request: 'request', session: 'session', message })
    try {
      if (protectedEndpoint) {
        assert.equal(await checkLocalMcpAuthentication({ transport, url: new URL(url), headers: {} }), 401)
        assert.equal(await checkLocalMcpAuthentication({ transport, url: new URL(url),
          headers: { Authorization: 'Bearer synthetic-rejected-token' } }), 403)
      }
      const handshake = await send({
        method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {},
          clientInfo: { name: 'Synthetic client', version: '1' } },
      })
      assert.ok('result' in handshake)
      assert.deepEqual(await send({ method: 'tools/list' }), {
        result: { tools: [{ name: 'inventory', inputSchema: { type: 'object' } }] },
      })
      assert.deepEqual(await send({ method: 'tools/call', params: { name: 'inventory', arguments: {} } }), {
        result: { content: [{ type: 'text', text: 'Three synthetic items' }] },
      })
      await send(null)
      if (transport === 'http') assert.equal(deletedSession, true)
      assert.deepEqual(await send({ method: 'tools/list' }), { missing: true })
    } finally {
      abort.abort()
      await local.close()
      endpoint.closeAllConnections()
      await new Promise<void>(resolve => endpoint.close(() => resolve()))
    }
  })
}
