<template>
  <SharingPanel :key="itemId" :state="state" :editable="editable && Boolean(state?.can_manage)"
    :loading="loading" :saving="saving" :error="error" @save="save" @reload="load">
    <template #avatar="{ recipient, size }">
      <slot name="avatar" :recipient="recipient" :size="size">
        <PersonAvatar :name="recipient.label" :avatar-url="recipient.avatar_url" :size="size" />
      </slot>
    </template>
  </SharingPanel>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { PersonAvatar } from '@/core/util/facade'
import { SharingPanel } from '../panel'
import type { SharingDraft } from '../sharing'
import type { SharingState, SharingUpdate } from '../types'

const props = defineProps<{ itemId: string; editable: boolean; lockVersion?: number;
  reader: (id: string) => Promise<SharingState>;
  writer: (id: string, data: SharingUpdate) => Promise<SharingState>
}>()
const emit = defineEmits<{ changed: [state: SharingState]; permission: [value: boolean] }>()
const state = ref<SharingState | null>(null)
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
    const result = await props.reader(props.itemId)
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
    const result = await props.writer(props.itemId, {
      ...draft, expected_lock_version: state.value.lock_version,
    })
    if (current !== generation) return
    state.value = result
    emit('permission', result.can_manage)
    emit('changed', result)
  } catch {
    if (current === generation) error.value = true
  } finally {
    if (current === generation) saving.value = false
  }
}
watch(() => [props.itemId, props.reader, props.writer], () => {
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
