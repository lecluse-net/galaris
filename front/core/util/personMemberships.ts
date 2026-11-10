import { onBeforeUnmount, ref } from 'vue'
import { onReadSessionChanged } from './sessionResources'
import type { MemberTeams } from './groupMemberOptions'

interface PersonMembershipProvider {
  readMemberships(kind: string, signal: AbortSignal): Promise<MemberTeams[]>
}
// Application composition follows the resource-detail and resource-topic providers.
const providers = import.meta.glob<PersonMembershipProvider>('../../personMemberships.ts')

export function usePersonMemberships(kind: string) {
  const members = ref<MemberTeams[]>([])
  let controller: AbortController | undefined
  let opened = false
  function cancel(): void { controller?.abort(); controller = undefined }
  function close(): void { opened = false; cancel() }
  async function open(): Promise<void> {
    opened = true
    cancel()
    const request = new AbortController()
    controller = request
    try {
      const provider = Object.values(providers)[0]
      if (!provider) return
      const result = await (await provider()).readMemberships(kind, request.signal)
      if (!request.signal.aborted) members.value = result
    } catch { /* Membership display must not remove the consumer's eligible choices. */ }
    finally { if (controller === request) controller = undefined }
  }
  const unsubscribe = onReadSessionChanged(authenticated => {
    cancel(); members.value = []
    if (opened && authenticated) void open()
  })
  onBeforeUnmount(() => { cancel(); unsubscribe() })
  return { members, open, close }
}
