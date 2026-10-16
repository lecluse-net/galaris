<template>
  <SharingPanel :state="state" :editable="editable" :loading="loading" :error="error" @save="emit('update:modelValue', $event)" @reload="load">
    <template #avatar="{ recipient, size }">
      <AgentAvatar v-if="recipient.kind === 'agent'" :agent-id="recipient.id" :name="recipient.label" :has-avatar="recipient.has_avatar" :size="size" />
      <PersonAvatar v-else :name="recipient.label" :avatar-url="recipient.avatar_url" :size="size" />
    </template>
  </SharingPanel>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AgentAvatar } from '@/app/agent'
import { PersonAvatar, SharingPanel, type SharingDraft, type SharingState } from '@/core/util'
import type { DocumentSharing } from '@/app/memory'
import { nativeProcessService as service } from '../services/nativeProcessService'
const props = defineProps<{ modelValue: SharingDraft; editable: boolean; agentId: number | null; owner: 'user' | 'agent' }>()
const emit = defineEmits<{ 'update:modelValue': [draft: SharingDraft] }>()
const catalog = ref<DocumentSharing | null>(null), loading = ref(false), error = ref(false)
let generation = 0
const state = computed<SharingState | null>(() => catalog.value ? { ...catalog.value, ...props.modelValue,
  grants: props.modelValue.grants.map(grant => ({
    ...catalog.value!.options.find(option => option.kind === grant.kind && option.id === grant.id),
    label: catalog.value!.options.find(option => option.kind === grant.kind && option.id === grant.id)?.label ?? `#${grant.id}`,
    ...grant,
  })),
} : null)
async function load(): Promise<void> {
  const current = ++generation, agentId = props.agentId
  catalog.value = null; error.value = false
  if (agentId === null || !props.editable) { loading.value = false; return }
  loading.value = true
  try {
    const result = await service.sharingOptions(agentId, props.owner)
    if (current === generation) {
      catalog.value = result
      const grants = props.modelValue.grants.filter(grant => grant.kind !== result.owner?.kind || grant.id !== result.owner.id)
      if (grants.length !== props.modelValue.grants.length) emit('update:modelValue', { ...props.modelValue, grants })
    }
  } catch { if (current === generation) error.value = true }
  finally { if (current === generation) loading.value = false }
}
watch(() => [props.agentId, props.owner, props.editable], () => { void load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
