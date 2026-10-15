<template>
  <SharingPanel :state="state" :editable="editable && Boolean(state?.can_manage)" :loading="loading" :saving="saving" :error="error" @save="save" @reload="load" />
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { SharingPanel, type SharingDraft } from '@/core/util'
import { datasetService as service } from '../services/datasetService'
import type { DatasetSharing } from '../types'
const props = defineProps<{ id: string; lockVersion: number; editable: boolean }>()
const emit = defineEmits<{ changed: [state: DatasetSharing] }>()
const state = ref<DatasetSharing | null>(null), loading = ref(false), saving = ref(false), error = ref(false)
let generation = 0
async function load(): Promise<void> {
  if (saving.value) return
  const token = ++generation; loading.value = true; error.value = false
  try { const result = await service.sharing(props.id); if (token === generation) state.value = result }
  catch { if (token === generation) error.value = true }
  finally { if (token === generation) loading.value = false }
}
async function save(draft: SharingDraft): Promise<void> {
  if (!state.value?.can_manage || !props.editable || loading.value || saving.value) return
  const token = generation; saving.value = true; error.value = false
  try { const result = await service.share(props.id, draft, state.value.lock_version); if (token !== generation) return; state.value = result; emit('changed', result) }
  catch { if (token === generation) error.value = true }
  finally { if (token === generation) saving.value = false }
}
watch(() => props.id, () => { generation++; state.value = null; saving.value = false; void load() }, { immediate: true })
watch(() => props.lockVersion, value => { if (value !== state.value?.lock_version) void load() })
onBeforeUnmount(() => { generation++ })
</script>
