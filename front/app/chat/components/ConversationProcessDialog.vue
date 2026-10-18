<template>
  <ResourceDetailDialog v-if="open && process"
    :target="{ kind: process.tool_code === 'galaris' ? 'process_run' : 'external_process_run', id: process.id, title: processLabel }" @close="open = false" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ResourceDetailDialog } from '@/core/util'
import type { ConversationProcess } from '../types'
const open = defineModel<boolean>({ required: true })
const { process } = defineProps<{ process: ConversationProcess | null }>()
const processLabel = computed(() => process?.process_label || process?.workflow_id || '')
</script>
