<template>
  <q-btn v-if="compact" flat dense no-caps to="/llm/usage" class="budget-gauge--compact"
    :aria-label="t('inferenceBudget.compactSummary', { summary: description, percentage })" :title="description">
    <span class="budget-gauge__period">{{ t(`inferenceBudget.shortPeriod.${props.envelope.period}`) }}</span>
    <q-linear-progress :value="ratio" :style="progressStyle" rounded size="8px" aria-hidden="true" />
    <span class="budget-gauge__percentage">{{ percentage }}</span>
    <q-tooltip>{{ description }}</q-tooltip>
  </q-btn>
  <div v-else :title="description">
    <div class="text-caption q-mb-xs">{{ amountLabel }}</div>
    <q-linear-progress :value="ratio" :style="progressStyle" rounded size="6px" :aria-label="description" />
    <q-tooltip>{{ description }}</q-tooltip>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { formatDollars, solaireCss } from '@/core/util/facade'
import type { Envelope } from '../services/budgetService'

const props = defineProps<{ envelope: Envelope; compact?: boolean }>()
const { t, locale } = useI18n()
const $q = useQuasar()
const total = computed(() => Number(props.envelope.limit) + Number(props.envelope.granted))
const usage = computed(() => props.envelope.limit === null ? 0 :
  total.value === 0 ? 1 : Number(props.envelope.spent) / total.value)
const ratio = computed(() => Math.min(usage.value, 1))
const percentage = computed(() => new Intl.NumberFormat(locale.value, { style: 'percent' }).format(usage.value))
const tone = computed(() => {
  if (ratio.value >= 0.95) return 'red'
  if (ratio.value >= 0.8) return 'orange'
  if (ratio.value >= 0.5) return 'blue'
  return 'green'
})
const progressStyle = computed(() => ({
  color: solaireCss[tone.value].accent,
  backgroundColor: solaireCss[tone.value][$q.dark.isActive ? 'dark' : 'light'],
}))
const currency = (value: number) => formatDollars(value, locale.value, { maximumFractionDigits: 6 })
const amountLabel = computed(() => t('inferenceBudget.amount', {
  spent: currency(Number(props.envelope.spent)), limit: currency(total.value),
}))
const renewal = computed(() => props.envelope.resets_at ? t('inferenceBudget.reset', {
  time: new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(props.envelope.resets_at)),
}) : t('inferenceBudget.sessionPending'))
const description = computed(() => t('inferenceBudget.summary', {
  period: t(`inferenceBudget.${props.envelope.period}`), amount: amountLabel.value, renewal: renewal.value,
}))
</script>

<style scoped>
.budget-gauge--compact {
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: subgrid;
  min-height: 0;
  padding: 2px 0;
  font-size: 10px;
  line-height: 1;
}
.budget-gauge--compact :deep(.q-btn__content) {
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: subgrid;
  align-items: center;
}
.budget-gauge__period { text-align: start; }
.budget-gauge__percentage {
  text-align: end;
  font-variant-numeric: tabular-nums;
}
@container sidebar-budget (max-width: 100px) {
  .budget-gauge__period, .budget-gauge__percentage { display: none; }
  .budget-gauge--compact :deep(.q-linear-progress) { grid-column: 1 / -1; }
}
</style>
