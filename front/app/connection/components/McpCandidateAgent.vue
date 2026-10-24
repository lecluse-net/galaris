<template>
  <AgentSelect v-model="model" :options="options" :label="label" outlined />
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { AgentSelect, useAgentChoices } from '@/app/agent'

defineProps<{ label: string }>()
const model = defineModel<number | null>({ required: true })
const agents = useAgentChoices()
onMounted(() => agents.fetchAgents())
const options = computed(() => agents.agents.map(agent => ({
  value: agent.id, label: agent.label, hasAvatar: agent.has_avatar,
})))
</script>
