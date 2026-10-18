<template>
  <div v-if="loading" class="flex flex-center q-pa-xl"><q-spinner color="primary" size="42px" /></div>
  <q-banner v-else-if="error" role="alert" class="q-ma-md">{{ error }}<template #action><q-btn outline :label="t('common.retry')" @click="retry++" /></template></q-banner>
  <AgentManagement v-else-if="agent" :preview-agent-id="agent.id" @deleted="emit('deleted')" />
</template>
<script setup lang="ts">
import { ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { defineAsyncView } from '@/core/util'
import { agentService, type Agent } from '../services/agentService'
const AgentManagement = defineAsyncView(() => import('../pages/index.vue'))

const { agentId } = defineProps<{ agentId: number }>()
const emit = defineEmits<{ loaded: [title: string]; deleted: [] }>()
const { t } = useI18n()
const agent = shallowRef<Agent | null>(null)
const loading = ref(false), error = ref(''), retry = ref(0)
watch([() => agentId, retry], async ([id], _, onCleanup) => {
  const request = new AbortController()
  onCleanup(() => request.abort())
  agent.value = null; error.value = ''; loading.value = true
  try {
    const { data } = await agentService.getAgent(id, request.signal)
    if (request.signal.aborted) return
    agent.value = data
    emit('loaded', `${data.first_name} ${data.last_name}`.trim())
  } catch { if (!request.signal.aborted) error.value = t('common.anError') }
  finally { if (!request.signal.aborted) loading.value = false }
}, { immediate: true })
</script>
