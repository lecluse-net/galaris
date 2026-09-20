<template>
  <section>
    <q-banner v-if="run.stop_reason === 'budget_exhausted'" class="q-my-md">{{ t('evaluation.insights.budgetStopped') }}</q-banner>
    <q-expansion-item v-if="run.repetitions > 1" :label="t('evaluation.insights.stability')" default-opened>
      <p class="q-pa-sm">{{ t('evaluation.insights.stabilityHelp') }}</p>
      <q-list bordered separator>
        <q-item v-for="row in stabilityRows" :key="row.id"><q-item-section>
          <q-item-label>{{ row.name }}</q-item-label>
          <q-item-label>{{ t('evaluation.insights.stabilityCount', row) }}</q-item-label>
          <q-item-label>{{ t('evaluation.insights.spread', { mean: format(row.mean), min: format(row.min), max: format(row.max), deviation: format(row.deviation) }) }}</q-item-label>
        </q-item-section></q-item>
      </q-list>
    </q-expansion-item>
    <q-select v-model="filter" :options="filters" emit-value map-options outlined :label="t('evaluation.insights.resultFilter')" class="q-my-md" />
    <p role="status">{{ t('evaluation.insights.displayed', { count: filtered.length, total: run.results.length }) }}</p>
    <q-expansion-item v-for="result in filtered" :key="result.id" v-model="expanded[result.id]" :label="result.case_snapshot.name" :caption="t('evaluation.insights.attempt', { number: result.repetition ?? 1 }) + ' · ' + t('evaluation.contract.status.' + (result.verdict ?? 'pending')) + ' · ' + format(result.score_percent)">
      <div v-if="expanded[result.id]" class="q-pa-md">
        <q-banner v-if="result.error || result.judge_output?.error" class="q-mb-md">{{ result.error || result.judge_output?.error }}</q-banner>
        <p v-if="result.judge_output?.explanation">{{ result.judge_output.explanation }}</p>
        <div v-if="isCritical(result)" class="critical q-pa-sm q-mb-md"><strong>{{ t('evaluation.insights.critical') }}</strong>
          <p v-for="failure in result.judge_output?.critical_failures" :key="failure">{{ failure }}</p>
        </div>
        <div class="result-columns">
          <section><h3>{{ t('evaluation.contract.result') }}</h3><LabReadableValue :value="result.actual_output" /></section>
          <section><h3>{{ t('evaluation.insights.dimensions') }}</h3>
            <div v-for="dimension in result.judge_output?.dimensions" :key="dimension.code" class="dimension">
              <strong>{{ dimensionLabel(dimension.code) }} · {{ format(dimension.score_percent) }}</strong>
              <p>{{ dimension.assessment }}</p>
            </div>
            <p v-if="!result.judge_output?.dimensions?.length">{{ t('evaluation.contract.unjudged') }}</p>
            <h3>{{ t('evaluation.insights.checks') }}</h3>
            <div v-for="check in objectiveChecks(result)" :key="check.code" class="q-mb-sm">
              <q-icon :name="check.passed ? 'check_circle' : 'error'" :style="{ color: check.passed ? solaire.green.accent : solaire.red.accent }" />
              <strong>{{ t(check.passed ? 'evaluation.insights.checkPassed' : 'evaluation.insights.checkFailed') }}</strong> · {{ check.detail }}
            </div>
          </section>
        </div>
        <q-expansion-item :label="t('evaluation.contract.effectiveInput')"><LabReadableValue :value="result.case_snapshot.resolved_input ?? result.case_snapshot.input_data" /></q-expansion-item>
        <q-expansion-item :label="t('evaluation.contract.reference')"><LabReadableValue :value="result.case_snapshot.expected_output" /></q-expansion-item>
        <q-expansion-item :label="t('evaluation.insights.raw')"><JsonEditor :model-value="JSON.stringify(result, null, 2)" language="json" readonly :visible-lines="12" /></q-expansion-item>
      </div>
    </q-expansion-item>
  </section>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { JsonEditor, solaireCss as solaire } from '@/core/util'
import type { LabRun } from '../services/labWorkbenchService'
import { isCritical, objectiveChecks, stability } from '../resultPresentation'
import LabReadableValue from './LabReadableValue.vue'
const { run } = defineProps<{ run: LabRun }>()
const { t } = useI18n()
const filter = ref('all')
const expanded = ref<Record<string, boolean>>({})
const filters = computed(() => ['all', 'failed', 'critical', 'unjudged'].map(value => ({ value, label: t('evaluation.insights.filters.' + value) })))
const filtered = computed(() => run.results.filter(result => filter.value === 'all' || (filter.value === 'failed' && (result.verdict === 'fail' || result.error)) || (filter.value === 'critical' && isCritical(result)) || (filter.value === 'unjudged' && result.score_percent == null)))
const stabilityRows = computed(() => stability(run.results, run.repetitions ?? 1))
const format = (value: number | null) => value == null ? '—' : value.toFixed(1)
const dimensionLabel = (code: string) => (run.campaigns?.[0]?.configuration.rubric ?? run.configuration_snapshot.rubric)?.dimensions.find(dim => dim.code === code)?.label ?? code
</script>
<style scoped>
.result-columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 24px; }
h3 { font-size: 1rem; font-weight: 600; margin-block: 12px; }
.critical { border-left: 4px solid v-bind('solaire.red.accent'); background: v-bind('solaire.red.light'); }
.body--dark .critical { background: v-bind('solaire.red.dark'); }
.dimension { margin-bottom: 16px; }
</style>
