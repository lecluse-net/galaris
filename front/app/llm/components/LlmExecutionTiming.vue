<template>
  <section class="q-mt-sm text-caption" :aria-label="t('llmTiming.title')">
    <div class="text-weight-medium">{{ t('llmTiming.title') }}</div>
    <dl class="q-my-sm">
      <div v-for="stage in stages" :key="stage.key" class="row q-col-gutter-sm">
        <dt class="col-8">{{ t(`llmTiming.${stage.key}`) }}</dt>
        <dd class="col-4 q-ma-none">{{ duration(stage.seconds) }}</dd>
      </div>
    </dl>
    <div>{{ t('llmTiming.explanation') }}</div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { LLMExecutionTiming } from '../types'

const { timing } = defineProps<{ timing: LLMExecutionTiming }>()
const { t, locale } = useI18n()
const stages = computed(() => [
  { key: 'firstOutput', seconds: timing.first_output_seconds },
  { key: 'calls', seconds: timing.call_seconds_before_output },
  { key: 'between', seconds: timing.between_calls_seconds },
])
function duration(seconds: number | null): string {
  return seconds == null ? t('llmTiming.unknown') : t('llmTiming.seconds', {
    value: new Intl.NumberFormat(locale.value, { maximumFractionDigits: 3 }).format(seconds),
  })
}
</script>
