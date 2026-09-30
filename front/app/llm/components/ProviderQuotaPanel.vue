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
      <div v-if="loading" role="status">{{ t('llm.quota.loading') }}</div>
      <div v-else-if="failed" role="alert">
        {{ t('llm.quota.unavailable') }}
        <div v-if="unavailableHint" class="text-caption q-mt-xs">{{ unavailableHint }}</div>
      </div>
      <template v-else-if="quota">
        <div class="text-caption q-mb-md">{{ t(quota.scope === 'api_key' ? 'llm.quota.apiKey' : 'llm.quota.accountWide') }}</div>
        <div v-if="!quota.windows.length">{{ t('llm.quota.empty') }}</div>
        <div v-for="window in quota.windows" :key="`${window.name}:${window.unit}`" class="q-mb-md">
          <div class="row justify-between q-gutter-xs q-mb-xs">
            <span>{{ windowLabel(window) }}</span>
            <span v-if="window.used_percent != null">{{ t('llm.quota.used', { percent: formatNumber(window.used_percent) }) }}</span>
          </div>
          <q-linear-progress
            v-if="window.used_percent != null"
            rounded size="8px" :value="Math.min(1, Math.max(0, window.used_percent / 100))"
            :style="{ color: quotaColor(window.used_percent) }"
            :aria-label="windowLabel(window)"
          />
          <div v-if="window.used != null" class="text-caption q-mt-xs">
            {{ t('llm.quota.amountUsed', { amount: formatAmount(window.used, window.unit) }) }}
          </div>
          <div v-if="window.limit != null" class="text-caption">
            {{ t('llm.quota.amountLimit', { amount: formatAmount(window.limit, window.unit) }) }}
          </div>
          <div v-if="window.remaining != null" class="text-weight-medium q-mt-xs">
            {{ t('llm.quota.amountRemaining', { amount: formatAmount(window.remaining, window.unit) }) }}
          </div>
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
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useInterval } from 'quasar'
import { useI18n } from 'vue-i18n'
import { solaireCss } from '@/core/util'
import llmProviderService, { type ProviderQuota, type ProviderQuotaWindow } from '../services/llmProviderService'

const props = defineProps<{ providerId: number; refreshKey?: string | null; unavailableHint?: string }>()
const { t, locale } = useI18n()
const quota = ref<ProviderQuota | null>(null)
const loading = ref(false)
const failed = ref(false)
const { registerInterval, removeInterval } = useInterval()
let request: AbortController | undefined

function startAutoRefresh(): void {
  registerInterval(() => {
    if (!loading.value) void load()
  }, 5 * 60 * 1000)
}

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

function formatAmount(value: number, unit: ProviderQuotaWindow['unit']): string {
  if (unit === 'USD' || unit === 'CNY') {
    return new Intl.NumberFormat(locale.value, {
      style: 'currency', currency: unit, currencyDisplay: 'code', maximumFractionDigits: 4,
    }).format(value)
  }
  return t('llm.quota.creditAmount', { count: formatNumber(value) })
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

watch(() => [props.providerId, props.refreshKey], load, { immediate: true })
onMounted(startAutoRefresh)
onActivated(startAutoRefresh)
onDeactivated(removeInterval)
onBeforeUnmount(() => request?.abort())
</script>
