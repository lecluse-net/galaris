<template>
  <div>
    <SettingsBlock :title="t('harnesses.preferences.executionLimits')"
      :description="t('harnesses.preferences.executionLimitsHint')" icon="speed">
      <SettingsFields :fields="executionLimitFields" :columns="2" />
    </SettingsBlock>
    <q-spinner v-if="loading" color="primary" />
    <q-banner v-else-if="failed" role="alert">
      {{ t('harnesses.policy.error') }}
      <template #action><q-btn flat :label="t('common.retry')" @click="load" /></template>
    </q-banner>
    <HarnessPipelineSettings v-else :configurations="configurations" />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { SettingsBlock, SettingsFields } from '@/core/params'
import { harnessService, type HarnessExecutionConfiguration } from '../services/harnessService'
import { executionLimitFields } from '../runtimeSettings'
import HarnessPipelineSettings from './HarnessPipelineSettings.vue'

const { t } = useI18n()
const configurations = ref<HarnessExecutionConfiguration[]>([])
const loading = ref(false)
const failed = ref(false)
let disposed = false

async function load(): Promise<void> {
  if (loading.value) return
  loading.value = true
  failed.value = false
  try {
    const result = await harnessService.executionConfigurations()
    if (!disposed) configurations.value = result.data
  } catch {
    if (!disposed) failed.value = true
  } finally {
    if (!disposed) loading.value = false
  }
}
onMounted(load)
onBeforeUnmount(() => { disposed = true })
</script>
