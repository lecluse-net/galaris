import type { ResourceDetailTarget } from '@/core/util'
import type { FileEntry } from './services/fileBrowserService'

export function parentDirectory(uri: string): string | null {
  const separator = uri.indexOf('://')
  if (separator < 0) return null
  const root = uri.slice(0, separator + 3)
  const path = uri.slice(separator + 3).replace(/\/$/, '')
  if (!path) return null
  const last = path.lastIndexOf('/')
  return last < 0 ? root : root + path.slice(0, last + 1)
}

export function resourceTarget(entry: FileEntry, agentId: number): ResourceDetailTarget | null {
  const match = /^(document|memory|data):\/\/([^/]+)$/.exec(entry.uri)
  if (match) return { kind: match[1] === 'data' ? 'dataset' : match[1]!, id: match[2]!, title: entry.name, agentId }
  const run = /^processus:\/\/run\/([^/]+)$/.exec(entry.uri)
  if (run) return { kind: 'process_run', id: run[1]!, title: entry.name, agentId }
  const business = /^galaris:\/\/(task|text|voice)\/([^/]+)$/.exec(entry.uri)
  if (!business) return null
  return { kind: business[1] === 'text' ? 'round' : business[1]!, id: business[2]!, title: entry.name, agentId }
}
