<template>
  <section v-if="comparison.economics">
    <h3>{{ t('evaluation.comparison.costs.title') }}</h3>
    <p>{{ t('evaluation.comparison.costs.economicsHelp') }}</p>
    <div class="row q-col-gutter-md">
      <div v-for="side in sides" :key="side" class="col-12 col-md-6">
        <h4>{{ t(side === 'left' ? 'evaluation.comparison.before' : 'evaluation.comparison.after') }}</h4>
        <template v-if="comparison.economics[side]">
          <p>{{ t('evaluation.comparison.costs.successes', { successes: comparison.economics[side].benchmark_successes, observations: comparison.economics[side].observations, unverified: comparison.economics[side].unverified, failed: comparison.economics[side].failed_candidates }) }}</p>
          <dl v-for="stage in stages" :key="stage">
            <dt>{{ t('evaluation.comparison.costs.' + stage) }}</dt>
            <dd>{{ format(comparison.economics[side][stage].recorded_cost) }} USD · {{ t('evaluation.comparison.costs.quality.' + comparison.economics[side][stage].quality) }}</dd>
            <dd>{{ t('evaluation.comparison.costs.coverage', { ...comparison.economics[side][stage] }) }}</dd>
          </dl>
          <dl><dt>{{ t('evaluation.comparison.costs.perSuccess') }}</dt><dd>{{ format(comparison.economics[side].cost_per_success) }}</dd></dl>
          <p v-if="comparison.economics[side].unavailable_reason">{{ t('evaluation.comparison.costs.reasons.' + comparison.economics[side].unavailable_reason) }}</p>
        </template>
      </div>
    </div>
    <p class="text-caption">{{ t('evaluation.comparison.costs.help') }}</p>
  </section>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { RunComparison } from '../services/labWorkbenchService'
defineProps<{ comparison: RunComparison }>()
const { t, locale } = useI18n()
const sides = ['left', 'right'] as const
const stages = ['candidate', 'judge'] as const
function format(value: number | null) {
  return value == null ? '—' : value.toLocaleString(locale.value, { maximumFractionDigits: 10 })
}
</script>
<style scoped>
h3, h4 { font-size: 1rem; font-weight: 600; }
dt { font-weight: 600; }
dd { margin: 0 0 12px; overflow-wrap: anywhere; }
</style>
