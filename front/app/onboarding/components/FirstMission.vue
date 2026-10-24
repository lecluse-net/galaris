<template>
  <q-card tag="section" flat bordered class="q-my-lg" :aria-label="t('onboarding.mission.title')">
    <q-card-section>
      <h2 class="text-h6 q-my-none">{{ t('onboarding.mission.title') }}</h2>
      <p>{{ t('onboarding.mission.description') }}</p>
      <p v-if="!canUseMission">{{ t('onboarding.mission.permission') }}</p>
      <template v-else>
        <q-banner v-if="error" role="alert" class="q-mb-md">{{ t('onboarding.mission.error') }}
          <template #action><q-btn outline :label="t('common.retry')" @click="retry" /></template>
        </q-banner>
        <template v-if="!job">
          <q-select v-model="agentId" outlined emit-value map-options :options="agents" option-label="display_name" option-value="agent_id"
            :loading="agentsLoading" :label="t('onboarding.mission.agent')" class="q-mb-md" :disable="busy" />
          <p v-if="!agentsLoading && !agents.length">{{ t('onboarding.mission.noAgent') }}</p>
          <q-select v-model="kind" outlined emit-value map-options :options="choices" :label="t('onboarding.mission.kind')" class="q-mb-md" :disable="busy" />
          <q-input v-model="text" type="textarea" outlined :label="t('onboarding.mission.request')" :disable="busy" maxlength="8000" />
          <p class="text-caption q-mt-sm">{{ t('onboarding.mission.cost') }}</p>
          <q-btn color="primary" :label="t('onboarding.mission.start')" :loading="busy" :disable="agentId === null || !text.trim()" @click="start" />
        </template>
        <template v-else>
          <p role="status">{{ t(`onboarding.mission.states.${state}`) }}</p>
          <q-list v-if="documents.length" bordered>
            <q-item v-for="document in documents" :key="document.id" clickable :to="`/documents?document_id=${encodeURIComponent(document.id)}`">
              <q-item-section avatar><q-icon name="description" /></q-item-section><q-item-section>{{ document.label }}</q-item-section>
            </q-item>
          </q-list>
          <q-card-actions>
            <q-btn outline color="primary" :label="t('onboarding.mission.open')" :to="`/chat?room=${encodeURIComponent(job.room)}`" />
            <q-btn outline icon="refresh" :label="t('onboarding.mission.refresh')" :loading="busy" @click="retry" />
            <q-btn v-if="state === 'complete'" outline :label="t('onboarding.mission.again')" @click="reset" />
          </q-card-actions>
        </template>
      </template>
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { useAuthStore } from '@/core/user'
import { firstMissionService, type MissionAgent, type MissionJob, type MissionTask, type MissionDocument } from '../services/firstMissionService'

const { t, locale } = useI18n(), access = usePrivilegeStore(), auth = useAuthStore()
const canChat = computed(() => access.hasPrivilege(privileges.CHAT_ACCESS))
const canUseMission = computed(() => canChat.value && access.hasPrivilege(privileges.CHAT_MANAGE)
  && access.hasPrivilege(privileges.CHAT_SEND)
  && (access.hasPrivilege(privileges.TASK_ACCESS) || access.hasPrivilege(privileges.TASK_EDIT))
  && (access.hasPrivilege(privileges.DOCUMENT_ACCESS) || access.hasPrivilege(privileges.DOCUMENT_EDIT) || access.hasPrivilege(privileges.DOCUMENT_ADMIN)))
const agents = ref<MissionAgent[]>([]), agentId = ref<number | null>(null), agentsLoading = ref(false), busy = ref(false), error = ref(false)
const kind = ref('summary'), text = ref(''), job = ref<MissionJob | null>(null), tasks = ref<MissionTask[]>([]), documents = ref<MissionDocument[]>([])
const choices = computed(() => ['summary', 'brief', 'plan'].map(value => ({ value, label: t(`onboarding.mission.kinds.${value}`) })))
const state = computed(() => {
  if (!job.value?.message) return 'sending'
  if (tasks.value.some(task => task.status === 'ERROR')) return 'failed'
  if (tasks.value.some(task => task.paused)) return 'waiting'
  if (tasks.value.length && tasks.value.every(task => task.status === 'SUCCESS')) return documents.value.length ? 'complete' : 'missing'
  return 'running'
})
let controller: AbortController | undefined, timer: ReturnType<typeof setTimeout> | undefined, disposed = false
let contextVersion = 0
const storageKey = () => `galaris:first-mission:${auth.user?.id ?? 'unknown'}`
function save(): void { try { if (job.value) sessionStorage.setItem(storageKey(), JSON.stringify(job.value)); else sessionStorage.removeItem(storageKey()) } catch { /* The live mission remains usable without storage. */ } }
function restore(): void {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(storageKey()) ?? 'null')
    if (typeof value !== 'object' || value === null) return
    const saved = value as Partial<MissionJob>
    if (typeof saved.room === 'string' && /^[0-9a-f-]{36}$/i.test(saved.room) && typeof saved.client === 'string'
      && typeof saved.text === 'string' && (saved.message === null || typeof saved.message === 'string')) job.value = saved as MissionJob
  } catch { /* Ignore obsolete or unavailable session storage. */ }
}
function reset(): void { job.value = null; tasks.value = []; documents.value = []; save() }
async function load(): Promise<void> {
  controller?.abort(); const request = new AbortController(); controller = request
  agentsLoading.value = true; error.value = false
  try { const result = await firstMissionService.agents(request.signal); if (!request.signal.aborted) { agents.value = result; if (!agents.value.some(agent => agent.agent_id === agentId.value)) agentId.value = agents.value[0]?.agent_id ?? null } }
  catch { if (!request.signal.aborted) error.value = true }
  finally { if (!request.signal.aborted) agentsLoading.value = false }
}
async function progress(): Promise<void> {
  clearTimeout(timer)
  if (!job.value?.message || !canUseMission.value || disposed) return
  controller?.abort(); const request = new AbortController(); controller = request
  const current = job.value
  try { const result = await firstMissionService.progress(current, request.signal)
    if (!request.signal.aborted && job.value === current) { tasks.value = result.tasks; documents.value = result.documents; error.value = false } }
  catch { if (!request.signal.aborted) error.value = true }
  finally { if (!request.signal.aborted && !disposed && !['complete', 'failed', 'missing'].includes(state.value)) timer = setTimeout(() => { void progress() }, 5000) }
}
async function send(): Promise<void> {
  if (!job.value || busy.value || !canUseMission.value) return
  const current = job.value, session = sessionGeneration()
  const version = contextVersion
  busy.value = true; error.value = false
  try { const id = await firstMissionService.send(current, locale.value)
    if (disposed || version !== contextVersion || session !== sessionGeneration() || job.value !== current) return
    current.message = id; save(); void progress() }
  catch { if (!disposed && version === contextVersion && session === sessionGeneration()) error.value = true }
  finally { if (!disposed && version === contextVersion && session === sessionGeneration()) busy.value = false }
}
async function start(): Promise<void> {
  if (agentId.value === null || busy.value || !text.value.trim() || !canUseMission.value) return
  busy.value = true; error.value = false
  const session = sessionGeneration(), prompt = text.value
  const version = contextVersion
  try { const room = await firstMissionService.createRoom(agentId.value, t('onboarding.mission.room'))
    if (disposed || version !== contextVersion || session !== sessionGeneration()) return
    job.value = { room, client: crypto.randomUUID(), text: prompt, message: null }; save()
  } catch { if (!disposed && version === contextVersion && session === sessionGeneration()) error.value = true }
  finally { if (!disposed && version === contextVersion && session === sessionGeneration()) busy.value = false }
  if (job.value && version === contextVersion && session === sessionGeneration() && !disposed) await send()
}
function retry(): void { if (job.value) { if (job.value.message) void progress(); else void send() } else void load() }
function sessionChanged(): void { contextVersion++; controller?.abort(); clearTimeout(timer); job.value = null; tasks.value = []; documents.value = []; agents.value = []; busy.value = false }
watch([kind, locale], () => { if (!job.value && !busy.value) text.value = t(`onboarding.mission.prompts.${kind.value}`) }, { immediate: true })
watch([canUseMission, () => access.loaded, () => access.privileges], ([allowed, loaded]) => {
  sessionChanged()
  if (allowed && loaded) { restore(); if (job.value?.message) void progress(); else void load() }
}, { immediate: true, deep: true })
onMounted(() => window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged))
onBeforeUnmount(() => { disposed = true; controller?.abort(); clearTimeout(timer); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged) })
</script>
