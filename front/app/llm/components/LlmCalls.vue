<template>
  <div class="q-mt-md">
    <q-banner v-if="props.error" rounded class="bg-negative text-white q-mb-md">
      {{ props.error }}
    </q-banner>

    <q-card v-if="visibleLoading && !visibleCalls.length" flat bordered>
      <q-card-section class="text-center text-grey">
        <q-spinner color="indigo" class="q-mr-sm" />{{ $t('task.llmCalls.loading') }}
      </q-card-section>
    </q-card>

    <div v-else-if="visibleCalls.length" class="llm-call-list">
      <LlmCallTaskDetail
        v-for="call in visibleCalls"
        :key="call.id"
        :call="call"
        :deletable="canPurge && Boolean(props.taskId)"
        @delete="requestDelete"
      />
    </div>

    <div v-else-if="!props.error" class="text-grey text-center q-pa-md">
      {{ $t('task.llmCalls.noCalls') }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { websocket } from '@/core/websocket'
import { sessionGeneration } from '@/core/api'
import { usePrivilegeStore, privileges } from '@/core/authorize'
import LlmCallTaskDetail from './LlmCallTaskDetail.vue'
import { llmCallService } from '../services/llmCallService'
import type { LLMCall } from '../types'

const props = withDefaults(defineProps<{
  taskId?: string
  externalCalls?: LLMCall[]
  loading?: boolean
  error?: string
}>(), {
  taskId: '',
  externalCalls: () => [],
  loading: false,
  error: '',
})
const { t } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const calls = ref<LLMCall[]>([])
const internalLoading = ref(false)
let generation = 0
let disposed = false
const canPurge = computed(() => privilegeStore.hasPrivilege(privileges.LLM_CALL_PURGE))
const visibleCalls = computed(() => props.taskId ? calls.value : props.externalCalls)
const visibleLoading = computed(() => props.taskId ? internalLoading.value : props.loading)

async function load(): Promise<void> {
  const request = ++generation
  const taskId = props.taskId
  const session = sessionGeneration()
  const current = () => !disposed && request === generation && taskId === props.taskId && session === sessionGeneration()
  calls.value = []
  internalLoading.value = Boolean(taskId)
  if (!taskId) return
  try {
    const result = await llmCallService.getByTask(taskId)
    if (current()) calls.value = result
  } catch {
    if (current()) $q.notify({ type: 'negative', message: t('llmCalls.loadError') })
  } finally {
    if (current()) internalLoading.value = false
  }
}

function upsert(call: LLMCall): void {
  if (!isTaskOwnedCall(call)) {
    removeCall(call.id)
    return
  }
  const index = calls.value.findIndex(item => item.id === call.id)
  if (index >= 0) calls.value[index] = call
  else calls.value.push(call)
  calls.value.sort((a, b) => a.started_at.localeCompare(b.started_at))
}

function isTaskOwnedCall(call: LLMCall): boolean {
  return call.task_id === props.taskId
    && (!call.process_run_id || call.purpose?.startsWith('agent.') === true)
    && !call.correlation_ref
}

const onCreate = (response: { data: LLMCall }) => upsert(response.data)
const onUpdate = (response: { data: LLMCall }) => upsert(response.data)
const onDelete = (response: { data: { id: string } }) => removeCall(response.data.id)

websocket.createWebsocket()
websocket.onEvent('llm_call', 'create', onCreate)
websocket.onEvent('llm_call', 'update', onUpdate)
websocket.onEvent('llm_call', 'delete', onDelete)

onBeforeUnmount(() => {
  disposed = true
  generation += 1
  websocket.offEvent('llm_call', 'create', onCreate)
  websocket.offEvent('llm_call', 'update', onUpdate)
  websocket.offEvent('llm_call', 'delete', onDelete)
})

watch(() => props.taskId, () => void load(), { immediate: true })

function removeCall(callId: string): void {
  calls.value = calls.value.filter(call => call.id !== callId)
}

function requestDelete(call: LLMCall): void {
  if (!canPurge.value) {
    $q.notify({ type: 'negative', message: t('llmCalls.notify.deleteDenied') })
    return
  }
  showConfirmationDialog({
    title: t('llmCalls.deleteConfirm'),
    message: t('llmCalls.deleteMessage'),
    cancel: { flat: true, label: t('llmCalls.cancel') },
    ok: { flat: true, color: 'negative', label: t('llmCalls.delete') },
  }).onOk(() => {
    void deleteCall(call.id)
  })
}

async function deleteCall(callId: string): Promise<void> {
  const request = generation
  const session = sessionGeneration()
  const current = () => !disposed && request === generation && session === sessionGeneration()
  try {
    await llmCallService.delete(callId)
    if (!current()) return
    removeCall(callId)
    $q.notify({ type: 'positive', message: t('llmCalls.notify.deleted') })
  } catch (reason) {
    if (current()) $q.notify({ type: 'negative', message: t('llmCalls.notify.deleteError') })
  }
}

</script>

<style scoped>
.llm-call-list {
  display: grid;
  gap: 16px;
  width: 100%;
  min-width: 0;
}
</style>
