<template>
  <section v-if="comparison.comparable" class="q-my-md">
    <template v-if="comparison.risks">
      <h3>{{ t('evaluation.comparison.risksTitle') }}</h3>
      <p>{{ t('evaluation.comparison.riskCoverage', { count: comparison.risks.assessed_pairs }) }}</p>
      <div class="row q-gutter-sm">
        <q-btn outline :disable="!comparison.risks.introduced_critical" :label="t('evaluation.comparison.criticalCount', { count: comparison.risks.introduced_critical })" @click="emit('focus', { focus: 'critical' })" />
        <q-btn outline :disable="!comparison.risks.pass_to_fail" :label="t('evaluation.comparison.verdictCount', { count: comparison.risks.pass_to_fail })" @click="emit('focus', { focus: 'verdict' })" />
      </div>
      <ul>
        <li v-for="dimension in comparison.risks.dimensions" :key="dimension.code" class="q-my-sm">
          {{ t('evaluation.comparison.dimensionSummary', { ...dimension, delta: format(dimension.mean_delta, 1) }) }}
          <q-btn v-if="dimension.decreased" flat dense :label="t('evaluation.comparison.dimensionCases', { code: dimension.code })" @click="emit('focus', { focus: 'dimension', dimension: dimension.code })" />
        </li>
      </ul>
    </template>
    <template v-if="comparison.performance">
      <h3>{{ t('evaluation.comparison.performanceTitle') }}</h3>
      <p>{{ t('evaluation.comparison.performanceHelp') }}</p>
      <dl>
        <template v-for="(metric, name) in comparison.performance" :key="name">
          <dt>{{ t('evaluation.comparison.performanceLabels.' + name) }}</dt>
          <dd>{{ t('evaluation.comparison.pairedMetric', { count: metric.pairs, before: format(metric.left_median, name === 'cost' ? 6 : 2), after: format(metric.right_median, name === 'cost' ? 6 : 2), delta: format(metric.median_delta, name === 'cost' ? 6 : 2) }) }}</dd>
        </template>
      </dl>
    </template>
  </section>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { ComparisonFilter, RunComparison } from '../services/labWorkbenchService'
defineProps<{ comparison: RunComparison }>()
const emit = defineEmits<{ focus: [filter: ComparisonFilter] }>()
const { t, locale } = useI18n()
function format(value: number | null, digits: number) {
  return value == null ? '—' : value.toLocaleString(locale.value, { maximumFractionDigits: digits })
}
</script>
<style scoped>
h3 { font-size: 1rem; line-height: 1.5; font-weight: 600; }
dt { font-weight: 600; }
dd { margin: 0 0 12px; }
li { overflow-wrap: anywhere; }
</style>
