import { onBeforeUnmount, reactive } from 'vue'
import { fileBrowserService, type FileEntry } from './services/fileBrowserService'

export interface DirectoryState {
  entries: FileEntry[]
  cursor: string | null
  loaded: boolean
  loading: boolean
  error: boolean
  incomplete: boolean
  version: number
}
export function useFileDirectories(agentId: number) {
  const directories = reactive(new Map<string, DirectoryState>())
  const requests = new Map<string, AbortController>()
  function directory(uri: string): DirectoryState {
    if (!directories.has(uri)) directories.set(uri, {
      entries: [], cursor: null, loaded: false, loading: false, error: false, incomplete: false, version: 0,
    })
    return directories.get(uri)!
  }
  async function load(uri: string, more = false): Promise<void> {
    const state = directory(uri)
    if (state.loading || (more && !state.cursor)) return
    const request = new AbortController()
    requests.set(uri, request)
    state.loading = true
    state.error = false
    try {
      const result = await fileBrowserService.list(agentId, uri, more ? state.cursor : null, request.signal)
      if (request.signal.aborted) return
      const entries = new Map((more ? state.entries : []).map(entry => [entry.uri, entry]))
      for (const entry of result.entries) entries.set(entry.uri, entry)
      state.entries = [...entries.values()]
      if (!more) state.version++
      // A repeating cursor cannot make progress and must never create an infinite request loop.
      state.incomplete = result.truncated && (!result.next_cursor || (more && result.next_cursor === state.cursor))
      state.cursor = state.incomplete ? null : result.next_cursor
      state.loaded = true
    } catch {
      if (!request.signal.aborted) state.error = true
    } finally {
      if (requests.get(uri) === request) { requests.delete(uri); state.loading = false }
    }
  }
  onBeforeUnmount(() => { for (const request of requests.values()) request.abort() })
  return { directory, load }
}
export type FileDirectories = ReturnType<typeof useFileDirectories>
