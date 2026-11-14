<template><pre>{{ text }}</pre></template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import type { ResourceViewerSource } from '@/core/util'
const { source } = defineProps<{ source: ResourceViewerSource }>()
const text = ref('')
let request: AbortController | undefined
watch(() => source.key, async () => {
  request?.abort(); const pending = new AbortController(); request = pending
  const value = await (await source.load(pending.signal)).text()
  if (!pending.signal.aborted) text.value = value
}, { immediate: true })
onBeforeUnmount(() => request?.abort())
</script>
