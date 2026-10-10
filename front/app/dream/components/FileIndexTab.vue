<template>
  <AgentSelect
    v-model="selectedAgentId"
    :options="agentOptions"
    :load-agents="false"
    :loading="agentStore.loading"
    :label="t('dream.indexing.agent')"
    behavior="menu"
    outlined
    dense
    options-dense
    class="q-my-md"
  />
  <q-banner v-if="agentStore.error" rounded class="q-mb-md">
    {{ t('dream.indexing.agentError') }}
    <q-btn flat :label="t('common.retry')" @click="loadAgents" />
  </q-banner>
  <div v-else-if="!agentStore.loading && !agentOptions.length" class="q-mb-md">{{ t('agent.noAgent') }}</div>
  <FileIndexPanel v-if="selectedAgentId !== null" :agent-id="selectedAgentId" :editable="canEdit" />
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { AgentSelect, useAgentStore, useAgentSelectionStore } from '@/app/agent'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import FileIndexPanel from './FileIndexPanel.vue'

const { t } = useI18n()
const route = useRoute()
const agentStore = useAgentStore()
const agentSelectionStore = useAgentSelectionStore()
const privilegeStore = usePrivilegeStore()
const selectedAgentId = defineModel<number | null>({ required: true })
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_EDIT))
const agentOptions = computed(() => agentStore.agents.map(agent => ({
  label: `${agent.first_name} ${agent.last_name}`.trim(),
  value: agent.id,
  hasAvatar: agent.has_avatar,
})))
let disposed = false

async function loadAgents(): Promise<void> {
  await agentStore.fetchAgents()
  if (disposed || agentStore.error) return
  if (agentStore.agents.some(agent => agent.id === selectedAgentId.value)) return
  const raw = Array.isArray(route.query.agent) ? route.query.agent[0] : route.query.agent
  const requested = raw ? Number(raw) : null
  selectedAgentId.value = agentStore.agents.some(agent => agent.id === requested)
    ? requested : agentSelectionStore.defaultAgentId(agentStore.agents)
}

onMounted(() => { void loadAgents() })
onBeforeUnmount(() => { disposed = true })
</script>
