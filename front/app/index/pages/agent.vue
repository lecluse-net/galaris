<route lang="json">
{ "path": "/agent" }
</route>
<template>
  <q-page class="agent-page q-pa-md">
    <PageHeader help-key="agents" :help-text="$t('contextHelpPages.agents')" :icon="navigationIcon('people')" :title="$t('nav.agent')" :description="$t('nav.agent_desc')" />

    <q-tabs v-model="activeTab" class="text-primary" active-color="primary" indicator-color="primary" align="left">
      <q-tab v-if="canViewAgents" name="agents" :label="$t('agent.tabAgents')" icon="people" />
      <q-tab v-if="canViewTeams" name="groups" :label="$t('team.title')" icon="groups" />
      <q-tab v-if="canViewAgents" name="titles" :label="$t('agent.tabTitles')" icon="badge" />
    </q-tabs>

    <q-separator />

    <template v-if="canViewAgents">
      <q-banner v-for="failure in catalogueFailures" :key="failure.action" role="alert" class="q-mt-md">
        {{ failure.label }} · {{ apiErrorDetail(failure.error) ?? t('common.anError') }}
        <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="retryCatalogue(failure.action)" /></template>
      </q-banner>
    </template>

    <q-tab-panels v-model="activeTab" animated keep-alive keep-alive-include="agents">
      <q-tab-panel v-if="canViewAgents" name="agents">
        <AgentWorkspace v-if="canViewAgents" :requested-agent-id="requestedAgentId" />
      </q-tab-panel>
      <q-tab-panel v-if="canViewTeams" name="groups"><TeamManager /></q-tab-panel>
      <q-tab-panel v-if="canViewAgents" name="titles"><AgentTitlesPanel /></q-tab-panel>
    </q-tab-panels>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { apiErrorDetail } from '@/core/api'
import { usePrivilegeStore } from '@/core/authorize'
import { navigationIcon } from '@/core/navigation'
import { TeamManager } from '@/core/team'
import { PageHeader } from '@/core/util'
import { invalidateSessionReads, storeRequests } from '@/core/util/facade'
import { useAgentStore } from '@/app/agent/facade'
import { AgentTitlesPanel } from '@/app/agent'
import AgentWorkspace from '../components/AgentWorkspace.vue'

const { t } = useI18n()
const agentStore = useAgentStore()
const catalogueRequests = storeRequests(agentStore)
type CatalogueRead = 'fetchAgents' | 'fetchTitles' | 'fetchGroups'
const catalogueFailures = computed(() => ([
  { action: 'fetchAgents' as const, label: t('agent.tabAgents') },
  { action: 'fetchTitles' as const, label: t('agent.tabTitles') },
  { action: 'fetchGroups' as const, label: t('team.title') },
]).flatMap(read => catalogueRequests[read.action]?.error ? [{ ...read, error: catalogueRequests[read.action].error }] : []))
async function retryCatalogue(action: CatalogueRead): Promise<void> { await agentStore[action](true) }
const privilegeStore = usePrivilegeStore()
const canViewAgents = computed(() => privilegeStore.hasPrivilege('AGENT_ACCESS') || privilegeStore.hasPrivilege('AGENT_EDIT'))
const canViewTeams = computed(() => privilegeStore.hasPrivilege('TEAM_ACCESS'))

const activeTab = ref('agents')
watch([canViewAgents, canViewTeams], () => {
  const allowed = [...(canViewAgents.value ? ['agents', 'titles'] : []), ...(canViewTeams.value ? ['groups'] : [])]
  if (!allowed.includes(activeTab.value)) activeTab.value = allowed[0] ?? ''
}, { immediate: true })

const route = useRoute()
const requestedAgentId = computed(() => {
  const value = route.query.agent_id
  return typeof value === 'string' && /^[1-9][0-9]*$/.test(value) ? Number(value) : undefined
})

// MCP administration may have changed the catalogue while the page was closed.
for (const group of ['agent-catalogue', 'agent-titles', 'agent-groups']) invalidateSessionReads(group)
watch(activeTab, async (tab, previous) => {
  if (tab === 'agents' && previous === 'groups' && canViewAgents.value) {
    await Promise.all([agentStore.fetchAgents(), agentStore.fetchGroups()])
  }
})
</script>

<style scoped>
@media (max-width: 599.98px) {
  .agent-page {
    padding: 8px;
  }
}
</style>
