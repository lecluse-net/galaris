<template>
  <ProcessPreview v-if="target" :uri="uri" :agent-id="agentId" inline />
  <a v-else-if="agent !== null" class="agent-citation-avatar" :href="richLinkHref(uri) ?? undefined" :aria-label="title" @click.stop.prevent="open = true"><ResourceThumbnail :uri="uri" :title="title" /></a>
  <ResourceDetailDialog v-if="open && detail" :target="detail" @close="open = false" />
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { defineAsyncView, ResourceThumbnail, ResourceDetailDialog, richLinkHref, richLinkTarget } from '@/core/util'
import { agentResourceId } from '@/app/agent'
import { processResourceTarget } from '@/app/process/interface'
const { uri, agentId = null, title = '' } = defineProps<{ uri: string; agentId?: number | null; title?: string }>()
const ProcessPreview = defineAsyncView(async () => (await import('@/app/process')).ProcessPreview)
const target = computed(() => processResourceTarget(uri))
const agent = computed(() => agentResourceId(uri))
const open = ref(false)
const detail = computed(() => richLinkTarget(uri, title, agentId))
</script>
<style scoped>
.agent-citation-avatar { display: block; width: 100%; height: 100%; }
</style>
