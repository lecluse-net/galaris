import type { ResourceDetailTarget } from '@/core/util'
import type { FileEntry } from './services/fileBrowserService'

/** Execution resources use their creation time as a readable, stable UI label. */
export function executionResourceLabel(entry: FileEntry, locale?: string): string | null {
  if (entry.is_collection || !/^galaris:\/\/(task|text|voice)\/[^/]+$/.test(entry.uri)) return null
  const createdAt = entry.metadata?.created_at
  if (typeof createdAt !== 'string' || !Number.isFinite(Date.parse(createdAt))) return null
  return new Intl.DateTimeFormat(locale, { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(createdAt))
}

/** Provider positions preserve meaningful order within virtual collections. */
export function compareFileEntries(left: FileEntry, right: FileEntry, locale: string): number {
  const position = (entry: FileEntry): number => typeof entry.metadata?.sort_order === 'number'
    && Number.isFinite(entry.metadata.sort_order) ? entry.metadata.sort_order : Number.MAX_VALUE
  return Number(right.is_collection) - Number(left.is_collection)
    || position(left) - position(right) || left.name.localeCompare(right.name, locale)
}

export function collectionLabel(uri: string, translate: (key: string) => string): string | null {
  return uri === 'document://folders/' ? translate('documents.collections.title') : skillCollectionLabel(uri, translate)
}

export function skillCollectionLabel(uri: string, translate: (key: string) => string): string | null {
  if (uri === 'galaris://skill/') return translate('files.skillLibrary')
  if (uri === 'galaris://skill/personnal/') return translate('files.personalSkills')
  if (uri === 'galaris://skill/_uncategorized/') return translate('skills.categories.none')
  return null
}

export function isSkillPackage(entry: FileEntry): boolean {
  if (!entry.is_collection) return false
  return /^galaris:\/\/skill\/(?!personnal(?:\/|$))[a-z0-9]+(?:-[a-z0-9]+)*\/?$/.test(entry.uri)
    || /^galaris:\/\/skill\/personnal\/[1-9][0-9]*\/[a-z0-9]+(?:-[a-z0-9]+)*\/?$/.test(entry.uri)
}

export function parentDirectory(uri: string): string | null {
  const separator = uri.indexOf('://')
  if (separator < 0) return null
  const root = uri.slice(0, separator + 3)
  const path = uri.slice(separator + 3).replace(/\/$/, '')
  if (!path) return null
  const last = path.lastIndexOf('/')
  return last < 0 ? root : root + path.slice(0, last + 1)
}

export function resourceTarget(entry: FileEntry, agentId: number, locale?: string): ResourceDetailTarget | null {
  if (isSkillPackage(entry)) return { kind: 'skill', id: entry.uri, title: entry.name, agentId }
  const match = /^(document|memory|data):\/\/([^/]+)$/.exec(entry.uri)
  if (match) return { kind: match[1] === 'data' ? 'dataset' : match[1]!, id: match[2]!, title: entry.name, agentId }
  const title = typeof entry.metadata?.label === 'string' ? entry.metadata.label : entry.name
  const run = /^galaris:\/\/processes\/runs\/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/.exec(entry.uri)
  if (run) return { kind: 'process_run', id: run[1]!, title, agentId }
  const process = /^galaris:\/\/process(?:es)?\/([A-Za-z_][A-Za-z0-9_.-]{0,254})$/.exec(entry.uri)
  if (process && (entry.uri.startsWith('galaris://processes/') || entry.metadata?.tool_code === 'galaris')) return { kind: 'process', id: process[1]!, title, agentId }
  const business = /^galaris:\/\/(task|text|voice|goal)\/([^/]+)$/.exec(entry.uri)
  if (!business) return null
  return { kind: business[1] === 'text' ? 'round' : business[1]!, id: business[2]!, title: executionResourceLabel(entry, locale) ?? entry.name, agentId }
}
