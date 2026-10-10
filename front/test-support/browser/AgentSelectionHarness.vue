<template>
  <MemoryPage v-if="page === 'memory'" />
  <ContactsPage v-else-if="page === 'contacts'" />
  <AgentSelect v-else :key="page" v-model="model" :options="options" :scope="scope"
    :load-agents="false" label="Agent choice" />
</template>

<script setup lang="ts">
import { AgentSelect } from '@/app/agent'
import type { AgentSelectionScope } from '@/app/agent/services/agentSelectionService'
import MemoryPage from '@/app/memory/pages/index.vue'
import ContactsPage from '@/app/memory/pages/contacts.vue'

const { page, options = [], scope = 'management' } = defineProps<{
  page: string
  options?: { value: number | null; label: string; disable?: boolean }[]
  scope?: AgentSelectionScope
}>()
const model = defineModel<number | null>({ default: null })
</script>
