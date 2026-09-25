<template>
  <q-card flat bordered>
    <q-card-section>
      <div class="row items-center no-wrap">
        <div class="text-weight-medium col">{{ t('llm.quota.title') }}</div>
        <q-btn
          flat round dense icon="refresh" :loading="loading"
          :aria-label="t('llm.quota.refresh')" @click="load"
        >
          <q-tooltip>{{ t('llm.quota.refresh') }}</q-tooltip>
        </q-btn>
      </div>
      <div class="text-caption q-mb-md">{{ t('llm.quota.accountWide') }}</div>
      <div v-if="loading" role="status">{{ t('llm.quota.loading') }}</div>
      <div v-else-if="failed" role="alert">{{ t('llm.quota.unavailable') }}</div>
      <template v-else-if="quota">
        <div v-if="!quota.windows.length">{{ t('llm.quota.empty') }}</div>
        <div v-for="window in quota.windows" :key="window.name" class="q-mb-md">
          <div class="row justify-between q-gutter-xs q-mb-xs">
            <span>{{ windowLabel(window) }}</span>
            <span>{{ t('llm.quota.used', { percent: formatNumber(window.used_percent) }) }}</span>
          </div>
          <q-linear-progress
            rounded size="8px" :value="window.used_percent / 100"
            :style="{ color: quotaColor(window.used_percent) }"
            :aria-label="windowLabel(window)"
          />
          <div v-if="window.resets_at" class="text-caption q-mt-xs">
            {{ t('llm.quota.resets', { date: formatDate(window.resets_at) }) }}
          </div>
        </div>
        <div class="text-caption">{{ t('llm.quota.checked', { date: formatDate(quota.checked_at) }) }}</div>
      </template>
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { solaireCss } from '@/core/util'
import llmProviderService, { type ProviderQuota, type ProviderQuotaWindow } from '../services/llmProviderService'

const props = defineProps<{ providerId: number }>()
const { t, locale } = useI18n()
const quota = ref<ProviderQuota | null>(null)
const loading = ref(false)
const failed = ref(false)
let request: AbortController | undefined

async function load(): Promise<void> {
  request?.abort()
  const current = new AbortController()
  request = current
  quota.value = null
  failed.value = false
  loading.value = true
  try {
    const { data } = await llmProviderService.getProviderQuota(props.providerId, current.signal)
    if (!current.signal.aborted) quota.value = data
  } catch {
    if (!current.signal.aborted) failed.value = true
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }).format(value)
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

function windowLabel(window: ProviderQuotaWindow): string {
  const seconds = window.window_seconds
  if (!seconds) return t(`llm.quota.${window.name}`)
  if (seconds % 86400 === 0) return t('llm.quota.days', { count: formatNumber(seconds / 86400) })
  if (seconds % 3600 === 0) return t('llm.quota.hours', { count: formatNumber(seconds / 3600) })
  return t('llm.quota.minutes', { count: formatNumber(seconds / 60) })
}

function quotaColor(percent: number): string {
  return percent >= 100 ? solaireCss.red.accent : percent >= 80 ? solaireCss.orange.accent : solaireCss.blue.accent
}

watch(() => props.providerId, load, { immediate: true })
onBeforeUnmount(() => request?.abort())
</script>
