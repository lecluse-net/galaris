import { readFile } from 'node:fs/promises'
import { mkdirSync, renameSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { serverOrigin } from './policy.ts'

export async function readServer(directory: string, development: boolean): Promise<string> {
  try {
    const data: unknown = JSON.parse(await readFile(path.join(directory, 'server.json'), 'utf8'))
    if (typeof data !== 'object' || data === null || !('server' in data)) return ''
    return serverOrigin(data.server, development)
  } catch { return '' }
}

/** Failed writes leave the last working server intact. No credentials are stored here. */
export function writeServer(directory: string, server: string): void {
  mkdirSync(directory, { recursive: true, mode: 0o700 })
  const target = path.join(directory, 'server.json')
  const temporary = `${target}.tmp`
  writeFileSync(temporary, `${JSON.stringify({ server })}\n`, { mode: 0o600 })
  renameSync(temporary, target)
}
