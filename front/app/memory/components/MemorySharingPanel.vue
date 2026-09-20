<template>
  <SharingPanel :key="itemId" :state="state" :editable="editable && Boolean(state?.can_manage)"
    :loading="loading" :saving="saving" :error="error" @save="save" @reload="load">
    <template #avatar="{ recipient, size }">
      <AgentAvatar v-if="recipient.kind === 'agent'" :agent-id="recipient.id" :name="recipient.label"
        :has-avatar="recipient.has_avatar" :size="size" />
      <PersonAvatar v-else :name="recipient.label" :avatar-url="recipient.avatar_url" :size="size" />
    </template>
  </SharingPanel>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { PersonAvatar, SharingPanel, type SharingDraft } from '@/core/util'
import { AgentAvatar } from '@/app/agent'
import { memoryService } from '../services/memoryService'
import type { DocumentSharing } from '../types'

const props = withDefaults(defineProps<{ itemId: string; editable: boolean; lockVersion?: number; resourceKind?: 'memory' | 'document' }>(), { resourceKind: 'memory' })
const emit = defineEmits<{ changed: []; permission: [value: boolean] }>()
const state = ref<DocumentSharing | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref(false)
let generation = 0

async function load(): Promise<void> {
  if (saving.value) return
  const current = ++generation
  loading.value = true
  error.value = false
  try {
    const result = props.resourceKind === 'document'
      ? await memoryService.documentSharing(props.itemId)
      : await memoryService.itemSharing(props.itemId)
    if (current !== generation) return
    state.value = result
    emit('permission', result.can_manage)
  } catch {
    if (current === generation) error.value = true
  } finally {
    if (current === generation) loading.value = false
  }
}
async function save(draft: SharingDraft): Promise<void> {
  if (!state.value?.can_manage || !props.editable || loading.value || saving.value) return
  const current = generation
  saving.value = true
  error.value = false
  try {
    const update = props.resourceKind === 'document' ? memoryService.updateDocumentSharingLevel : memoryService.updateItemSharing
    const result = await update(props.itemId, {
      ...draft, expected_lock_version: state.value.lock_version,
    })
    if (current !== generation) return
    state.value = result
    emit('permission', result.can_manage)
    emit('changed')
  } catch {
    if (current === generation) error.value = true
  } finally {
    if (current === generation) saving.value = false
  }
}
watch(() => [props.itemId, props.resourceKind], () => {
  generation++
  state.value = null
  saving.value = false
  void load()
}, { immediate: true })
watch(() => props.lockVersion, value => {
  if (value !== state.value?.lock_version) void load()
})
onBeforeUnmount(() => { generation++ })
</script>
