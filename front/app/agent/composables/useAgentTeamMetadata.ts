import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { getAgentSelection, type AgentSelectionOption, type AgentSelectionScope } from '../services/agentSelectionService'

/** Display metadata only: the consumer remains responsible for eligible choices. */
export function useAgentTeamMetadata(
  scope: () => AgentSelectionScope = () => 'management',
  provided: () => readonly AgentSelectionOption[] | undefined = () => undefined,
) {
  const metadata = ref<AgentSelectionOption[]>([])
  let controller: AbortController | undefined
  let opened = false
  function cancel(): void { controller?.abort(); controller = undefined }
  function close(): void { opened = false; cancel() }
  async function open(): Promise<void> {
    opened = true
    if (provided() !== undefined) return
    cancel()
    const request = new AbortController()
    controller = request
    try {
      const result = await getAgentSelection(scope(), request.signal)
      if (!request.signal.aborted) metadata.value = result
    } catch { /* Preserve eligible choices; retry grouping on reopening. */ }
    finally { if (controller === request) controller = undefined }
  }
  function invalidate(): void { cancel(); metadata.value = []; if (opened) void open() }
  watch(scope, invalidate)
  onMounted(() => window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, invalidate))
  onBeforeUnmount(() => { cancel(); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, invalidate) })
  return { metadata, open, close }
}
