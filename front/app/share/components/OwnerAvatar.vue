<template>
  <PersonAvatar :name="owner.label" :avatar-url="owner.kind === 'agent' ? agentUrl : owner.avatar_url" :size="size" />
</template>
<script lang="ts">
import { createSessionImageCache } from '@/core/util/facade'

const avatars = createSessionImageCache('agent-avatar', 300_000)
</script>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { PersonAvatar } from '@/core/util/facade'
import { onReadSessionChanged, onSessionReadInvalidation } from '@/core/util/facade'
import type { OwnerOption } from '../owners'

const { owner, size = '28px' } = defineProps<{ owner: OwnerOption; size?: string }>()
const agentUrl = ref('')
let request: AbortController | undefined
function clear(): void {
  request?.abort()
  if (agentUrl.value) URL.revokeObjectURL(agentUrl.value)
  agentUrl.value = ''
}
async function load(): Promise<void> {
  clear()
  if (owner.kind !== 'agent' || !owner.has_avatar) return
  const current = new AbortController()
  const id = owner.id
  request = current
  try {
    const blob = await avatars.read(`/agents/${id}/avatar`, current.signal)
    if (!current.signal.aborted) agentUrl.value = URL.createObjectURL(blob)
  } catch { /* Keep initials when an avatar is unavailable or the read was cancelled. */ }
}
watch(() => [owner.kind, owner.id, owner.has_avatar], () => { void load() }, { immediate: true })
const unsubscribe = onSessionReadInvalidation('agent-avatar', () => { void load() })
const unsubscribeSession = onReadSessionChanged(authenticated => {
  clear()
  if (authenticated) void load()
})
onBeforeUnmount(() => { clear(); unsubscribe(); unsubscribeSession() })
</script>
