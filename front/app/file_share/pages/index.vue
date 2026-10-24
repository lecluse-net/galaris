<route lang="json">
{ "path": "/files" }
</route>

<template>
  <q-page class="files-page q-pa-md" :class="{ 'viewport-page--desktop': !$q.screen.lt.md }" :style-fn="pageStyle">
    <PageHeader icon="folder_open" :title="t('nav.files')" :description="t('nav.files_desc')" />
    <q-tabs v-model="tab" align="left" class="text-primary">
      <q-tab v-if="canBrowse" name="files" icon="folder_open" :label="t('nav.files')" />
      <q-tab v-if="canIndex" name="indexing" icon="manage_search" :label="t('dream.tabs.indexing')" />
    </q-tabs>
    <div v-if="agentId !== null" class="row items-center no-wrap q-gutter-md q-mb-md">
      <AgentSelect v-model="agentId" class="file-agent col" :options="agentOptions" :load-agents="false" outlined dense :label="t('agent.selectPlaceholder')" :loading="loading" />
      <span v-if="browser && browser.loadedCount > 0" class="file-loaded text-caption">{{ t('files.loaded', { count: browser.loadedCount }) }}</span>
    </div>
    <q-banner v-if="error" role="alert" class="q-mb-md">
      {{ t('files.agentError') }}
      <template #action><q-btn outline :label="t('common.retry')" @click="loadAgents" /></template>
    </q-banner>
    <AgentFileBrowser v-if="agentId !== null && tab === 'files' && canBrowse" ref="browser" :key="`${agentId}:${session}`" :agent-id="agentId" :initial-uri="resourceUri" @navigate="locationChanged" />
    <div v-else-if="agentId !== null && tab === 'indexing' && canIndex" class="file-index-content">
      <FileIndexPanel :key="`${agentId}:${session}`" :agent-id="agentId" :editable="canRunIndex" />
    </div>
    <section v-else class="file-agent-picker" :aria-label="t('files.chooseAgent')">
      <p class="text-body1">{{ t('files.chooseAgent') }}</p>
      <div v-if="loading" class="row items-center q-gutter-sm" role="status">
        <q-spinner color="primary" size="24px" /><span>{{ t('files.loading') }}</span>
      </div>
      <div v-else-if="!error" class="file-agent-cards">
        <q-btn v-for="agent in agents" :key="agent.id" outline rounded no-caps padding="12px 16px" class="file-agent-card"
          :aria-label="t('files.openAgent', { name: agent.label })" @click="agentId = agent.id">
          <AgentAvatar :agent-id="agent.id" :name="agent.label" :has-avatar="agent.has_avatar" size="44px" />
          <span class="col ellipsis text-left" :title="agent.label">{{ agent.label }}</span>
          <FolderIcon size="32px" />
        </q-btn>
        <p v-if="!agents.length" class="text-body2">{{ t('agent.noAgent') }}</p>
      </div>
    </section>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { AgentAvatar, AgentSelect, getAgentSelection, type AgentSelectionOption } from '@/app/agent'
import { FolderIcon, PageHeader } from '@/core/util'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import AgentFileBrowser from '../components/AgentFileBrowser.vue'
import FileIndexPanel from '../components/FileIndexPanel.vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const privilegeStore = usePrivilegeStore()
const canBrowse = computed(() => privilegeStore.hasAnyPrivilege([privileges.FILE_ACCESS, privileges.FILE_EDIT]))
const canIndex = computed(() => privilegeStore.hasAnyPrivilege([privileges.FILE_INDEX_ACCESS, privileges.FILE_INDEX_RUN]))
const canRunIndex = computed(() => privilegeStore.hasPrivilege(privileges.FILE_INDEX_RUN))
const tab = ref('files')
watch([canBrowse, canIndex], () => {
  if (tab.value === 'files' && !canBrowse.value && canIndex.value) tab.value = 'indexing'
  else if (tab.value === 'indexing' && !canIndex.value) tab.value = 'files'
}, { immediate: true })
const resourceUri = computed(() => typeof route.query.uri === 'string' && route.query.uri.length <= 4096 ? route.query.uri : null)
function pageStyle(offset: number, height: number): { height: string } {
  return { height: `${Math.max(0, height - offset)}px` }
}
const agents = ref<AgentSelectionOption[]>([])
const agentId = computed<number | null>({
  get: () => typeof route.query.agent_id === 'string'
    ? agents.value.find(agent => String(agent.id) === route.query.agent_id)?.id ?? null : null,
  set: value => {
    if (value === agentId.value) return
    void router.push({ path: route.path, query: { ...route.query, agent_id: value === null ? undefined : String(value), uri: undefined } })
  },
})
const loading = ref(false), error = ref(false), session = ref(0)
const browser = useTemplateRef<InstanceType<typeof AgentFileBrowser>>('browser')
onBeforeRouteUpdate((to, from) => to.query.agent_id === from.query.agent_id && to.query.uri === from.query.uri
  ? true : browser.value?.canLeave() ?? true)
let controller: AbortController | undefined
const agentOptions = computed(() => agents.value.map(agent => ({ value: agent.id, label: agent.label, hasAvatar: agent.has_avatar })))
function locationChanged(uri: string, replace = false): void {
  if (agentId.value === null || uri === (resourceUri.value ?? '')) return
  const destination = { path: route.path, query: { ...route.query, agent_id: String(agentId.value), uri: uri || undefined } }
  void (replace ? router.replace(destination) : router.push(destination))
}
async function loadAgents(): Promise<void> {
  controller?.abort()
  const request = new AbortController(); controller = request
  loading.value = true; error.value = false
  try {
    const result = await getAgentSelection('management', request.signal)
    if (request.signal.aborted) return
    agents.value = result
  } catch { if (!request.signal.aborted) error.value = true }
  finally { if (!request.signal.aborted) loading.value = false }
}
function sessionChanged(event: Event): void {
  session.value++; controller?.abort(); agents.value = []
  if ((event as CustomEvent<string | null>).detail) void loadAgents()
}
onMounted(() => { void loadAgents(); window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged) })
onBeforeUnmount(() => { controller?.abort(); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged) })
</script>

<style scoped>
.files-page { display: flex; flex-direction: column; overflow: hidden; padding-bottom: 0; }
.files-page > :not(.file-browser-container):not(.file-agent-picker) { flex-shrink: 0; }
.file-agent { max-width: 420px; }
.file-index-content { min-height: 0; overflow: auto; flex: 1; }
.file-loaded { flex-shrink: 0; color: var(--solaire-gray-accent); }
.file-agent-picker { --file-agent-surface: #fff; --file-agent-border: rgba(35, 46, 66, .14); --file-agent-text: #252b36; flex: 1; min-height: 0; overflow: auto; padding-bottom: 16px; }
.file-agent-cards { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 12px; }
.file-agent-card { width: 280px; max-width: 100%; color: var(--file-agent-border); background: var(--file-agent-surface) !important; --q-primary: var(--solaire-blue-accent); }
.file-agent-card :deep(.q-btn__content) { flex-wrap: nowrap; gap: 12px; color: var(--file-agent-text); }
:global(body.body--dark .file-agent-picker) { --file-agent-surface: #1b1e23; --file-agent-border: rgba(255, 255, 255, .15); --file-agent-text: #e7ebf2; }
@media (max-width: 1023px) {
  .file-agent-card { width: 100%; }
}
</style>
