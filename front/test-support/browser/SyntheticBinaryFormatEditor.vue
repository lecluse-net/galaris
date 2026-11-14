<template>
  <section>
    <q-input v-model="content" outlined type="textarea" label="Synthetic binary content" :readonly="source.readonly" />
    <q-btn color="primary" label="Save synthetic binary" :disable="source.readonly" :loading="saving" @click="save" />
    <q-banner v-if="failed" role="alert">Synthetic save failed; draft retained</q-banner>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { DocumentContentSource } from '@/app/document'
const { source } = defineProps<{ source: DocumentContentSource }>()
const content = ref(''), saved = ref(''), saving = ref(false), failed = ref(false)
const dirty = computed(() => content.value !== saved.value)
let request: AbortController | undefined, activeSave: Promise<void> | undefined
watch(() => source.key, async () => {
  request?.abort(); const pending = new AbortController(); request = pending
  const value = await (await source.load(pending.signal)).text()
  if (!pending.signal.aborted) content.value = saved.value = value
}, { immediate: true })
function save(): void {
  activeSave = (async () => {
    saving.value = true; failed.value = false
    try { await source.save(new Blob([content.value]), source.revision, new AbortController().signal); saved.value = content.value }
    catch { failed.value = true }
    finally { saving.value = false }
  })()
}
defineExpose({ flush: async () => { await activeSave; return !dirty.value }, discardDraft: () => { content.value = saved.value } })
onBeforeUnmount(() => request?.abort())
</script>
