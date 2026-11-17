<template>
  <PersonAvatar :name="owner.label" :avatar-url="owner.kind === 'agent' ? agentUrl : owner.avatar_url" :size="size" />
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { PersonAvatar, onReadSessionChanged, onSessionReadInvalidation, readSessionImage } from '@/core/util/facade'
import type { OwnerOption } from '../owners'

const { owner, size = '28px' } = defineProps<{ owner: OwnerOption; size?: string }>()
const agentUrl = ref('')
let request: AbortController | undefined
let signedOut = false
function clear(): void {
  request?.abort()
  if (agentUrl.value) URL.revokeObjectURL(agentUrl.value)
  agentUrl.value = ''
}
async function load(refresh = false): Promise<void> {
  clear()
  if (signedOut || owner.kind !== 'agent' || (!refresh && owner.has_avatar === false)) return
  const current = new AbortController()
  const id = owner.id
  request = current
  try {
    const blob = await readSessionImage('agent-avatar', String(id), `/agents/${id}/avatar`, current.signal)
    if (blob && !current.signal.aborted) agentUrl.value = URL.createObjectURL(blob)
  } catch { /* Keep initials when an avatar is unavailable or the read was cancelled. */ }
}
watch([() => owner.kind, () => owner.id, () => owner.has_avatar], () => { void load() }, { immediate: true })
const unsubscribe = onSessionReadInvalidation('agent-avatar', key => {
  if (key === undefined || key === String(owner.id)) void load(key !== undefined)
})
const unsubscribeSession = onReadSessionChanged(authenticated => {
  signedOut = !authenticated
  void load()
})
onBeforeUnmount(() => { clear(); unsubscribe(); unsubscribeSession() })
</script>
