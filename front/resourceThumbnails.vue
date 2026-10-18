<template>
  <AgentAvatar v-if="resourceAgent !== null" class="resource-agent-thumbnail" square :agent-id="resourceAgent" :name="title" :has-avatar="true" />
  <ProcessThumbnail v-else-if="target" :uri="uri" :agent-id="agentId" :title="title" />
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { defineAsyncView } from '@/core/util'
import { agentResourceId } from '@/app/agent'
import { processResourceTarget } from '@/app/process/interface'
const { uri, agentId = null, title } = defineProps<{ uri: string; agentId?: number | null; title: string }>()
const AgentAvatar = defineAsyncView(async () => (await import('@/app/agent')).AgentAvatar)
const ProcessThumbnail = defineAsyncView(async () => (await import('@/app/process')).ProcessThumbnail)
const resourceAgent = computed(() => agentResourceId(uri))
const target = computed(() => processResourceTarget(uri))
</script>
<style scoped>
.resource-agent-thumbnail { width: 100%; height: 100%; min-height: inherit; }
.resource-agent-thumbnail :deep(img) { object-fit: cover; }
</style>
