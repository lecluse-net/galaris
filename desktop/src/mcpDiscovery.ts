import { createHash } from 'node:crypto'
import { open, stat } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { parse } from 'smol-toml'
import type { LocalMcpSummary } from './contracts.ts'

type Stdio = { transport: 'stdio'; command: string; args: string[]; cwd: string; env: Record<string, string> }
type Http = { transport: 'http' | 'sse'; url: URL; headers: Record<string, string> }
export type LocalMcp = { summary: LocalMcpSummary; fingerprint: string; options: Stdio | Http }

const maxFileSize = 1024 * 1024
const maxServers = 64
const unresolved = /\$\{(?:input|command|workspaceFolder|env):|\$\{workspaceFolder\}/

function record(value: unknown): Record<string, unknown> | undefined {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
}

function stringMap(value: unknown): Record<string, string> | undefined {
  if (value === undefined) return {}
  const entries = Object.entries(record(value) ?? {})
  if (!record(value) || entries.some(([, text]) => typeof text !== 'string' || unresolved.test(text))) return
  return Object.fromEntries(entries) as Record<string, string>
}

function optionsFor(input: Record<string, unknown>, file: string): LocalMcp['options'] | undefined {
  if (input.enabled === false || input.disabled === true) return
  if (typeof input.url === 'string') {
    const url = new URL(input.url)
    if (!['http:', 'https:'].includes(url.protocol) || !['127.0.0.1', '[::1]', 'localhost'].includes(url.hostname)
      || url.username || url.password || url.hash || unresolved.test(input.url)) return
    const headers = stringMap(input.headers ?? input.http_headers)
    const envHeaders = stringMap(input.env_http_headers)
    if (!headers || !envHeaders) return
    const values: Record<string, string> = { ...headers }
    for (const [name, key] of Object.entries(envHeaders)) {
      const value = process.env[key]
      if (value !== undefined) values[name] = value
    }
    if (typeof input.bearer_token_env_var === 'string') {
      const value = process.env[input.bearer_token_env_var]
      if (value) values.Authorization = 'Bearer ' + value
    }
    return { transport: (input.type === 'sse' || (input.type === undefined && url.pathname.endsWith('/sse'))) ? 'sse' : 'http',
      url, headers: Object.fromEntries(new Headers(values)) }
  }
  if (typeof input.command !== 'string' || !input.command.trim() || input.command.includes('\0') || unresolved.test(input.command)) return
  const args: unknown = input.args ?? []
  if (!Array.isArray(args) || !args.every((arg): arg is string => typeof arg === 'string'
    && !arg.includes('\0') && !unresolved.test(arg))) return
  if (input.cwd !== undefined && (typeof input.cwd !== 'string' || unresolved.test(input.cwd))) return
  const env = stringMap(input.env)
  if (!env) return
  if (Array.isArray(input.env_vars)) {
    for (const key of input.env_vars) {
      if (typeof key === 'string' && /^[a-zA-Z_]\w*$/.test(key) && !Object.hasOwn(env, key)) {
        const value = process.env[key]
        if (value !== undefined) Object.defineProperty(env, key, { value, enumerable: true })
      }
    }
  }
  const cwd = typeof input.cwd === 'string' ? path.resolve(path.dirname(file), input.cwd) : os.homedir()
  const command = input.command.startsWith('.') ? path.resolve(cwd, input.command) : input.command
  return { transport: 'stdio', command, args, cwd, env }
}

function hash(value: unknown): string {
  return createHash('sha256').update(JSON.stringify(value)).digest('hex')
}

export function parseMcpFile(text: string, file: string, source: string): LocalMcp[] {
  const isToml = path.extname(file).toLowerCase() === '.toml'
  const config = record(isToml ? parse(text) : JSON.parse(text))
  const servers = record(config?.mcpServers ?? config?.mcp_servers ?? config?.servers)
  const found: LocalMcp[] = []
  for (const [name, value] of Object.entries(servers ?? {}).slice(0, maxServers)) {
    const input = record(value)
    if (!input || !name.trim() || name.length > 120) continue
    try {
      const options = optionsFor(input, file)
      if (!options) continue
      const summary = { id: hash([file, name]), name, source, transport: options.transport }
      found.push({ summary, fingerprint: hash(options), options })
    } catch {
      // Ignore malformed entries independently so the rest of the file remains discoverable.
    }
  }
  return found
}

async function readMcpFile(file: string, source: string): Promise<LocalMcp[]> {
  const metadata = await stat(file)
  if (!metadata.isFile() || metadata.size > maxFileSize) throw new Error('Invalid MCP file')
  const handle = await open(file, 'r')
  try {
    const buffer = Buffer.alloc(maxFileSize + 1)
    const { bytesRead } = await handle.read(buffer, 0, buffer.length)
    if (bytesRead > maxFileSize) throw new Error('MCP file is too large')
    return parseMcpFile(buffer.toString('utf8', 0, bytesRead), file, source)
  } finally {
    await handle.close()
  }
}

export async function discoverLocalMcp(imported: readonly string[]): Promise<{ entries: LocalMcp[]; unreadable: number }> {
  const home = os.homedir()
  const settings = process.platform === 'win32' ? process.env.APPDATA || path.join(home, 'AppData', 'Roaming')
    : process.platform === 'darwin' ? path.join(home, 'Library', 'Application Support')
      : process.env.XDG_CONFIG_HOME || path.join(home, '.config')
  const files = new Map([
    [path.join(settings, 'Claude', 'claude_desktop_config.json'), 'Claude Desktop'],
    [path.join(process.env.CODEX_HOME || path.join(home, '.codex'), 'config.toml'), 'Codex'],
    [path.join(settings, 'Code', 'User', 'mcp.json'), 'Visual Studio Code'],
    [path.join(home, '.cursor', 'mcp.json'), 'Cursor'],
    ...imported.map(file => [file, path.basename(file)] as const),
  ])
  const results = await Promise.all([...files].map(async ([file, source]) => {
    try { return await readMcpFile(file, source) } catch (error) {
      return (error as NodeJS.ErrnoException).code === 'ENOENT' && !imported.includes(file) ? [] : undefined
    }
  }))
  return { entries: results.flatMap(result => result ?? []).slice(0, maxServers),
    unreadable: results.filter(result => result === undefined).length }
}
