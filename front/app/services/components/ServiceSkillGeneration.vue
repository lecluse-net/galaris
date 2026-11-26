<template>
  <div v-show="visible" class="q-pa-md">
    <q-btn v-if="!taskId" outline color="primary" icon="auto_awesome"
      :label="t('services.skillGeneration.generate')" :loading="submitting" @click="generate" />
    <div v-else class="row items-center q-gutter-sm">
      <span role="status">{{ t('services.skillGeneration.queued') }}</span>
      <q-btn outline color="primary" icon="open_in_new" :label="t('services.skillGeneration.openTask')"
        :to="{ path: '/task', query: { task_id: taskId } }" v-close-popup />
    </div>
    <p v-if="error" class="text-negative q-mt-sm q-mb-none" role="alert">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { isAxiosError } from 'axios'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import serviceApi from '../services/serviceApi'

const { serviceId, visible } = defineProps<{ serviceId: number; visible: boolean }>()
const { t } = useI18n()
const submitting = ref(false)
const taskId = ref('')
const error = ref('')
let operationId: string | undefined

async function generate(): Promise<void> {
  if (submitting.value || taskId.value) return
  submitting.value = true
  error.value = ''
  try {
    operationId ??= crypto.randomUUID()
    taskId.value = await serviceApi.generateSkill(serviceId, operationId)
  } catch (cause) {
    const detail = isAxiosError<{ detail?: unknown }>(cause) ? cause.response?.data?.detail : undefined
    error.value = typeof detail === 'string' ? detail : t('services.skillGeneration.error')
  } finally {
    submitting.value = false
  }
}
</script>
