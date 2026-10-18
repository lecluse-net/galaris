<template>
  <ProcessPreview v-if="target" ref="process" :uri="uri" :agent-id="agentId" inline />
  <a v-else-if="agent !== null" ref="avatar" class="agent-citation-avatar" :href="richLinkHref(uri) ?? undefined" :aria-label="title" @click.stop.prevent="open = true"><ResourceThumbnail :uri="uri" :title="title" /></a>
  <ResourceDetailDialog v-if="open && detail" :target="detail" @close="open = false" />
</template>
<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, useTemplateRef } from 'vue'
import { defineAsyncView, ResourceThumbnail, ResourceDetailDialog, richLinkHref, richLinkTarget, captureElementRendering, type RegisterDocumentCapture, type RenderedDocumentCapture } from '@/core/util'
import { agentResourceId } from '@/app/agent'
import { processResourceTarget } from '@/app/process/interface'
const { uri, agentId = null, title = '', registerSnapshot } = defineProps<{ uri: string; agentId?: number | null; title?: string; registerSnapshot?: RegisterDocumentCapture }>()
const ProcessPreview = defineAsyncView(async () => (await import('@/app/process')).ProcessPreview)
const target = computed(() => processResourceTarget(uri))
const agent = computed(() => agentResourceId(uri))
const open = ref(false)
const detail = computed(() => richLinkTarget(uri, title, agentId))
const process = useTemplateRef<{ capture: RenderedDocumentCapture }>('process'), avatar = useTemplateRef('avatar')
async function capture(signal: AbortSignal): Promise<string> {
  if (target.value && process.value) return process.value.capture(signal)
  const element = avatar.value?.querySelector<HTMLElement>('.q-avatar')
  if (!element) throw new Error('Agent rendering unavailable')
  return captureElementRendering(element, signal)
}
onMounted(() => registerSnapshot?.(capture))
onBeforeUnmount(() => registerSnapshot?.(undefined))
</script>
<style scoped>
.agent-citation-avatar { display: block; width: 100%; height: 100%; }
</style>
