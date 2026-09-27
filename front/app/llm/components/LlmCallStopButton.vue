<template>
  <q-btn
    v-if="canStop"
    flat dense round size="sm" color="negative" icon="stop_circle"
    :loading="pending"
    :title="t('llmCalls.stopCall')"
    :aria-label="t('llmCalls.stopCall')"
    @click.stop="requestStop"
  />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { sessionGeneration } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { showConfirmationDialog } from '@/core/util'
import { llmCallService } from '../services/llmCallService'
import type { LLMCall } from '../types'

const props = defineProps<{ call: LLMCall }>()
const { t } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const pending = ref(false)
let disposed = false
onBeforeUnmount(() => { disposed = true })
const canStop = computed(() => props.call.status === 'running'
  && Boolean(props.call.inference_attempt_id)
  && privilegeStore.hasPrivilege(privileges.TASK_EDIT))

function requestStop(): void {
  if (!canStop.value || pending.value) return
  const callId = props.call.id
  const session = sessionGeneration()
  showConfirmationDialog({
    title: t('llmCalls.stopCall'),
    message: t('llmCalls.stopMessage'),
    cancel: { flat: true, label: t('llmCalls.cancel') },
    ok: { flat: true, color: 'negative', label: t('llmCalls.stopCall') },
  }).onOk(() => { void stop(callId, session) })
}

async function stop(callId: string, session: string): Promise<void> {
  const current = () => !disposed && props.call.id === callId && session === sessionGeneration()
  if (!current() || !canStop.value || pending.value) return
  pending.value = true
  try {
    await llmCallService.stop(callId)
    if (current()) $q.notify({ type: 'positive', message: t('llmCalls.stopRequested') })
  } catch {
    if (current()) $q.notify({ type: 'negative', message: t('llmCalls.stopError') })
  } finally {
    if (!disposed) pending.value = false
  }
}
</script>
