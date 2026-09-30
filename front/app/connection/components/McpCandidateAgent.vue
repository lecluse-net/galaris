<template>
  <AgentSelect v-model="model" :options="options" :label="label" outlined />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { AgentSelect, useAgentStore } from '@/app/agent'

defineProps<{ label: string }>()
const model = defineModel<number | null>({ required: true })
const agents = useAgentStore()
const options = computed(() => agents.agents.map(agent => ({
  value: agent.id, label: `${agent.first_name} ${agent.last_name}`.trim(), hasAvatar: agent.has_avatar,
})))
</script>
