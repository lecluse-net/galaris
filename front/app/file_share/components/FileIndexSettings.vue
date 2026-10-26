<template>
  <AgentSelect
    v-model="selectedAgentId"
    :options="agentOptions"
    :load-agents="false"
    :loading="loading"
    :label="t('dream.indexing.agent')"
    behavior="menu"
    outlined
    dense
    options-dense
    class="q-my-md"
  />
  <q-banner v-if="error" rounded class="q-mb-md">
    {{ t('dream.indexing.agentError') }}
    <q-btn outline color="primary" :label="t('common.retry')" @click="loadAgents" />
  </q-banner>
  <div v-else-if="!loading && !agentOptions.length" class="q-mb-md">{{ t('agent.noAgent') }}</div>
  <FileIndexPanel v-if="selectedAgentId !== null" :agent-id="selectedAgentId" :editable="canEdit" />
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { AgentSelect, getAgentSelection, useAgentSelectionStore, type AgentSelectionOption } from '@/app/agent'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import FileIndexPanel from './FileIndexPanel.vue'

const { t } = useI18n()
const route = useRoute()
const agents = ref<AgentSelectionOption[]>([])
const loading = ref(false), error = ref(false)
const agentSelectionStore = useAgentSelectionStore()
const privilegeStore = usePrivilegeStore()
const selectedAgentId = defineModel<number | null>({ required: true })
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.FILE_INDEX_RUN))
const agentOptions = computed(() => agents.value.map(agent => ({
  label: agent.label,
  value: agent.id,
  hasAvatar: agent.has_avatar,
})))
let disposed = false

async function loadAgents(): Promise<void> {
  loading.value = true; error.value = false
  try {
    const result = await getAgentSelection('management')
    if (disposed) return
    agents.value = result
    if (agents.value.some(agent => agent.id === selectedAgentId.value)) return
    const query = route.query.agent_id ?? route.query.agent
    const raw = Array.isArray(query) ? query[0] : query
    const requested = raw ? Number(raw) : null
    selectedAgentId.value = agents.value.some(agent => agent.id === requested)
      ? requested : agentSelectionStore.defaultAgentId(agents.value)
  } catch { if (!disposed) error.value = true }
  finally { if (!disposed) loading.value = false }
}

onMounted(() => { void loadAgents() })
onBeforeUnmount(() => { disposed = true })
</script>
