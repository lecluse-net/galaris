import { onBeforeUnmount } from 'vue'
import { sessionGeneration } from '@/core/api'
import { websocket } from '@/core/websocket'
import { llmCallService } from './services/llmCallService'
import { applyLlmCallProgress, isNewerCallRevision, type LLMCallProgress } from './progress'
import type { LLMCall } from './types'
import { privileges, usePrivilegeStore } from '@/core/authorize'

/** Subscribe only while mounted; recover gaps once per visible call. */
export function useLlmCallProgress(select: (id: string) => LLMCall | undefined, apply: (call: LLMCall) => void): void {
  const privilegeStore = usePrivilegeStore()
  const pending = new Map<string, AbortController>()
  let disposed = false
  function receive(event: { data: LLMCallProgress }): void {
    if (!privilegeStore.hasAnyPrivilege([privileges.LLM_CALL_ACCESS, privileges.LLM_CALL_CONTROL])) return
    const progress = event.data
    const current = select(progress.id)
    if (!current) return
    const next = applyLlmCallProgress(current, progress)
    if (next) {
      if (next !== current) apply(next)
      return
    }
    if (pending.has(progress.id)) return
    const controller = new AbortController()
    pending.set(progress.id, controller)
    const session = sessionGeneration()
    void llmCallService.getById(progress.id, controller.signal).then(snapshot => {
      if (disposed || session !== sessionGeneration()
        || !privilegeStore.hasAnyPrivilege([privileges.LLM_CALL_ACCESS, privileges.LLM_CALL_CONTROL])) return
      const latest = select(progress.id)
      if (!latest || latest.status !== 'running') return
      if (isNewerCallRevision(latest.updated_at, snapshot.updated_at)) return
      apply(snapshot)
    }).catch(() => {
      // A later progress event retries; deletion, revocation and reconnect keep
      // their existing authoritative HTTP/terminal-event reconciliation.
    }).finally(() => pending.delete(progress.id))
  }
  websocket.onEvent('llm_call', 'progress', receive)
  onBeforeUnmount(() => {
    disposed = true
    for (const controller of pending.values()) controller.abort()
    pending.clear()
    websocket.offEvent('llm_call', 'progress', receive)
  })
}
