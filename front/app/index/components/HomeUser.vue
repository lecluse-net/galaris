<template>
  <q-page class="member-home q-pa-md">
    <div class="member-home__shell">
      <PageHeader icon="dashboard" :title="t('index.actionCenter.greeting', { name: auth.userDisplayName })"
        :description="t('index.userHome.intro')" />

      <div class="member-home__directory">
        <q-card tag="section" flat bordered aria-labelledby="home-teams-title">
          <q-card-section>
            <h2 id="home-teams-title" class="text-h6 q-ma-none">{{ t('index.userHome.teams') }}</h2>
            <div v-if="teamsLoading" role="status" class="q-mt-sm">
              <q-spinner color="primary" class="q-mr-sm" />{{ t('common.loading') }}
            </div>
            <q-banner v-else-if="teamsFailed" rounded role="alert" class="q-mt-sm">
              {{ t('index.userHome.teamsError') }}
              <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="teamRetry++" /></template>
            </q-banner>
            <ul v-else-if="teams.length" class="team-list q-mt-sm">
              <li v-for="team in teams" :key="team.id">
                <q-chip icon="groups" class="bg-solaire-blue-light">{{ team.name }}</q-chip>
              </li>
            </ul>
            <p v-else class="q-mt-sm q-mb-none">{{ t('index.userHome.noTeams') }}</p>
          </q-card-section>
        </q-card>

        <q-card v-if="canBrowseAgents" tag="section" flat bordered aria-labelledby="home-agents-title">
          <q-card-section>
            <h2 id="home-agents-title" class="text-h6 q-ma-none">{{ t('index.userHome.agents') }}</h2>
            <div v-if="agentsLoading" role="status" class="q-mt-sm">
              <q-spinner color="primary" class="q-mr-sm" />{{ t('common.loading') }}
            </div>
            <q-banner v-else-if="agentsFailed" rounded role="alert" class="q-mt-sm">
              {{ t('index.userHome.agentsError') }}
              <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="agentsRetry++" /></template>
            </q-banner>
            <p v-else-if="!agents.length" class="q-mt-sm q-mb-none">{{ t('index.userHome.noAgents') }}</p>
          </q-card-section>
          <q-list v-if="agents.length && !agentsLoading && !agentsFailed" separator>
            <q-item v-for="agent in agents" :key="agent.agent_id" clickable tag="button" type="button"
              class="agent-row full-width text-left" @click="selectedAgent = agent">
              <q-item-section avatar>
                <AgentAvatar :agent-id="agent.agent_id" :name="agent.display_name" dialogue />
              </q-item-section>
              <q-item-section><q-item-label>{{ agent.display_name }}</q-item-label></q-item-section>
              <q-item-section side><q-icon name="chevron_right" /></q-item-section>
            </q-item>
          </q-list>
          <ListPagination v-model:page="agentsPage"
            :page-size="agentsPageSize" :total="totalAgents" :loading="agentsLoading"
            :label="t('chat.home.agentPages')" :page-size-label="t('chat.home.perPage')" class="q-pb-md"
            @update:page-size="changePageSize" />
        </q-card>
      </div>

      <section v-if="access.loaded" aria-labelledby="home-uses-title" class="q-mt-lg">
        <h2 id="home-uses-title" class="text-h6 q-mb-md q-mt-none">{{ t('index.userHome.uses') }}</h2>
        <div v-if="destinations.length" class="member-home__uses">
          <q-card v-for="destination in destinations" :key="destination.to" flat bordered class="member-home__use">
            <q-card-section>
              <div class="member-home__use-heading">
                <q-icon v-if="destination.icon" :name="destination.icon" size="24px" color="primary" />
                <h3 class="text-subtitle1 text-weight-bold q-ma-none">{{ t(destination.label) }}</h3>
              </div>
              <p class="q-mt-sm q-mb-none">{{ t(destination.description) }}</p>
            </q-card-section>
            <q-card-actions align="right">
              <q-btn outline no-caps color="primary" icon-right="arrow_forward" :to="destination.to"
                :label="t('index.userHome.open', { section: t(destination.label) })" />
            </q-card-actions>
          </q-card>
        </div>
        <p v-else>{{ t('index.userHome.noUses') }}</p>
      </section>
      <q-banner v-else-if="!access.loading" rounded role="alert" class="q-mt-lg">
        {{ t('index.userHome.accessError') }}
        <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="access.loadPrivileges()" /></template>
      </q-banner>
    </div>
    <HomeAgentProfile v-if="canBrowseAgents && selectedAgent" :agent="selectedAgent" @close="selectedAgent = null" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useNavigation } from '@/core/navigation'
import { teamService } from '@/core/team'
import { useAuthStore } from '@/core/user'
import { ListPagination, PageHeader } from '@/core/util'
import { AgentAvatar } from '@/app/agent'
import { agentDialogueService, type DialogueAgent } from '@/app/agent/facade'
import HomeAgentProfile from './HomeAgentProfile.vue'

const { t } = useI18n()
const auth = useAuthStore()
const access = usePrivilegeStore()
const navigation = useNavigation()
const canBrowseAgents = computed(() => access.loaded && Boolean(navigation.findByRoute('/chat')))

const destinations = computed(() => [
  ...navigation.getSortedNodes(navigation.getTreeByRoot('act')),
  ...navigation.getSortedNodes(navigation.getTreeByRoot('knowledge')),
  navigation.findByRoute('/task'),
].flatMap(entry => {
  if (!entry?.to || !entry.label || !entry.description) return []
  const { to, label, icon } = entry
  let description = entry.description
  if (to === '/chat' && access.hasPrivilege(privileges.CHAT_SEND)) description = 'index.userHome.chatUse'
  if (to === '/documents') {
    description = access.hasPrivilege(privileges.DOCUMENT_EDIT) ? 'index.userHome.documentsEdit' : 'index.userHome.documentsRead'
  }
  return [{ to, label, icon, description }]
}))

const teams = ref<Awaited<ReturnType<typeof teamService.myTeams>>>([])
const teamsLoading = ref(true)
const teamsFailed = ref(false)
const teamRetry = ref(0)
watch([() => auth.user?.id, teamRetry], async ([userId], _, onCleanup) => {
  teams.value = []
  teamsFailed.value = false
  teamsLoading.value = false
  if (!userId) return
  const request = new AbortController()
  onCleanup(() => request.abort())
  teamsLoading.value = true
  try {
    const result = await teamService.myTeams(userId, request.signal)
    if (!request.signal.aborted) teams.value = result
  } catch {
    if (!request.signal.aborted) teamsFailed.value = true
  } finally {
    if (!request.signal.aborted) teamsLoading.value = false
  }
}, { immediate: true })

const agents = ref<DialogueAgent[]>([])
const agentsPage = ref(1)
const agentsPageSize = ref(50)
const totalAgents = ref(0)
const agentsRetry = ref(0)
const agentsLoading = ref(false)
const agentsFailed = ref(false)
const selectedAgent = ref<DialogueAgent | null>(null)

function changePageSize(size: number): void {
  agentsPage.value = 1
  agentsPageSize.value = size
}

watch([canBrowseAgents, () => access.privileges, agentsPage, agentsPageSize, agentsRetry], async ([allowed, , page, size], _, onCleanup) => {
  agents.value = []
  selectedAgent.value = null
  agentsFailed.value = false
  agentsLoading.value = false
  if (!allowed) {
    totalAgents.value = 0
    agentsPage.value = 1
    return
  }
  const request = new AbortController()
  onCleanup(() => request.abort())
  agentsLoading.value = true
  try {
    const result = await agentDialogueService.page(page, size, request.signal)
    if (request.signal.aborted) return
    totalAgents.value = result.total
    const lastPage = Math.max(1, Math.ceil(result.total / size))
    if (page > lastPage) agentsPage.value = lastPage
    else agents.value = result.agents
  } catch {
    if (!request.signal.aborted) agentsFailed.value = true
  } finally {
    if (!request.signal.aborted) agentsLoading.value = false
  }
}, { immediate: true })
</script>

<style scoped>
.member-home__shell { width: min(1120px, 100%); margin: 0 auto; }
.member-home__directory { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 16px; align-items: start; }
.member-home__uses { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 265px), 1fr)); gap: 16px; }
.member-home__use { display: flex; flex-direction: column; justify-content: space-between; }
.member-home__use-heading { display: flex; align-items: center; gap: 8px; }
.team-list { padding: 0; margin-bottom: 0; list-style: none; }
.team-list .q-chip { height: auto; max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
.agent-row { border: 0; background: transparent; color: inherit; }
</style>
