<template>
  <q-dialog v-model="opened">
    <q-card class="comparison-dialog galaris-dialog-card">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ t('evaluation.comparison.title') }}</div><q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section class="galaris-dialog-body">
        <p>{{ t('evaluation.comparison.help') }}</p>
        <div class="comparison-columns">
          <section v-for="side in sides" :key="side.key">
            <h3>{{ t('evaluation.comparison.' + side.key) }}</h3>
            <q-select v-model="side.datasetId" :options="datasets" option-value="id" option-label="name" emit-value map-options outlined :label="t('evaluation.comparison.dataset')" />
            <q-select v-model="side.runId" :options="side.runs.map(run => ({ value: run.id, label: runLabel(run) }))" emit-value map-options outlined :loading="side.loading" :disable="side.loading" :label="t('evaluation.comparison.run')" class="q-mt-sm" />
            <p class="text-caption">{{ t('evaluation.comparison.recentRuns') }}</p>
            <p v-if="side.datasetId && !side.loading && !side.error && !side.runs.length">{{ t('evaluation.comparison.noRuns') }}</p>
            <q-banner v-if="side.error" role="alert">{{ side.error }} <q-btn flat :label="t('evaluation.comparison.retry')" @click="loadRuns(side)" /></q-banner>
          </section>
        </div>
        <q-select v-model="axis" :options="axes" emit-value map-options outlined :label="t('evaluation.comparison.axis')" class="q-my-md" />
        <div class="row q-gutter-sm">
          <q-btn color="primary" icon="compare_arrows" :label="t('evaluation.comparison.compare')" :disable="!ready" :loading="loading" @click="compare(0)" />
          <q-btn flat icon="swap_horiz" :label="t('evaluation.comparison.swap')" :disable="!ready || loading" @click="swap" />
        </div>
        <q-banner v-if="error" role="alert" class="q-mt-md">{{ error }}</q-banner>
        <template v-if="result">
          <q-banner class="comparison-notice q-my-md" role="status">
            {{ t(result.comparable ? 'evaluation.comparison.compatible' : 'evaluation.comparison.incompatible') }}
            <ul v-if="result.blockers.length"><li v-for="blocker in result.blockers" :key="blocker">{{ t('evaluation.comparison.blockers.' + blocker) }}</li></ul>
          </q-banner>
          <p>{{ t('evaluation.comparison.descriptive') }}</p>
          <p v-if="incomplete" class="comparison-notice q-pa-sm">{{ t('evaluation.comparison.incomplete') }}</p>
          <p>{{ t('evaluation.comparison.progress', { before: result.left.completed_cases, beforeTotal: result.left.total_cases, after: result.right.completed_cases, afterTotal: result.right.total_cases }) }}</p>
          <template v-if="result.summary">
            <p>{{ t('evaluation.comparison.globalCoverage', result.summary) }}</p>
            <p>{{ t('evaluation.comparison.globalMissing', result.summary) }}</p>
            <p v-if="result.comparable">{{ t('evaluation.comparison.globalScores', result.summary) }}</p>
          </template>
          <p v-if="result.comparable">{{ t('evaluation.comparison.counts', counts) }}</p>
          <p v-else>{{ t('evaluation.comparison.noSummary') }}</p>
          <LabComparisonInsights :comparison="result" @focus="chooseFocus" />
          <p v-if="filter.focus !== 'all'">
            {{ t('evaluation.comparison.activeFocus.' + filter.focus, { code: filter.dimension ?? '' }) }}
            <q-btn flat :label="t('evaluation.comparison.allCases')" @click="chooseFocus({ focus: 'all' })" />
          </p>
          <p v-if="!result.items.length">{{ t('evaluation.comparison.empty') }}</p>
          <article v-for="item in result.items" :key="item.left_result_id" class="comparison-case q-my-md q-pa-md">
            <h3>{{ item.name || t('evaluation.comparison.unnamed') }} · {{ t('evaluation.insights.attempt', { number: item.repetition }) }}</h3>
            <p v-if="item.pairing !== 'matched'" class="comparison-notice q-pa-sm">{{ t('evaluation.comparison.pairing.' + item.pairing) }}</p>
            <p v-else>{{ t('evaluation.comparison.deltas', { score: delta(item.score_delta, 1), cost: delta(item.cost_delta, 6), duration: delta(item.duration_delta, 2) }) }}</p>
            <p v-if="item.introduced_critical" class="comparison-error">{{ t('evaluation.comparison.newCritical') }}</p>
            <p v-if="item.pass_to_fail" class="comparison-error">{{ t('evaluation.comparison.passToFail') }}</p>
            <p v-for="(change, code) in item.dimension_deltas" :key="code">{{ t('evaluation.comparison.dimensionDelta', { code, delta: delta(change, 1) }) }}</p>
            <q-expansion-item :label="t('evaluation.contract.effectiveInput')"><LabReadableValue :value="item.input" /></q-expansion-item>
            <q-expansion-item :label="t('evaluation.contract.reference')"><LabReadableValue :value="item.reference" /></q-expansion-item>
            <div class="comparison-columns q-mt-md">
              <section v-for="side in (['left', 'right'] as const)" :key="side">
                <h4>{{ t('evaluation.comparison.' + (side === 'left' ? 'before' : 'after')) }}</h4>
                <template v-if="side === 'left' || item.pairing === 'matched'">
                  <p>{{ t('evaluation.comparison.metrics', { score: number(item[`${side}_score`], 1), cost: number(item[`${side}_cost`], 6), duration: number(item[`${side}_duration`], 2) }) }}</p>
                  <p>{{ t('evaluation.comparison.firstOutput', { seconds: number(item[`${side}_first_output_seconds`], 2) }) }}</p>
                  <p>{{ item[`${side}_verdict`] ? t('evaluation.contract.status.' + item[`${side}_verdict`]) : t('evaluation.comparison.unjudged') }}</p>
                  <p v-if="item[`${side}_error`]" class="comparison-error">{{ item[`${side}_error`] }}</p>
                  <ul v-if="item[`${side}_judgment`]?.critical_failures?.length" class="comparison-error"><li v-for="failure in item[`${side}_judgment`]?.critical_failures" :key="failure">{{ failure }}</li></ul>
                  <LabReadableValue :value="item[`${side}_output`]" />
                  <q-expansion-item :label="t('evaluation.comparison.evidence')" class="q-mt-sm">
                    <LabReadableValue :value="item[`${side}_checks`]" /><LabReadableValue :value="item[`${side}_judgment`]" />
                  </q-expansion-item>
                </template>
                <p v-else>{{ t('evaluation.comparison.pairing.' + item.pairing) }}</p>
              </section>
            </div>
          </article>
          <div class="row items-center q-gutter-sm">
            <q-select v-model="limit" :options="[10, 20, 50, 100, 500]" outlined :label="t('evaluation.comparison.pageSize')" class="page-size" />
            <q-btn flat :label="t('evaluation.comparison.previous')" :disable="loading || offset === 0" @click="compare(Math.max(0, offset - limit))" />
            <span>{{ t('evaluation.comparison.page', { number: Math.floor(offset / limit) + 1 }) }}</span>
            <q-btn flat :label="t('evaluation.comparison.next')" :disable="loading || result.next_offset == null" @click="compare(result.next_offset ?? 0)" />
          </div>
        </template>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { solaireCss as solaire } from '@/core/util'
import { labWorkbenchService as api, type ComparisonAxis, type ComparisonFilter, type LabDataset, type LabKey, type LabRun, type RunComparison } from '../services/labWorkbenchService'
import LabReadableValue from './LabReadableValue.vue'
import LabComparisonInsights from './LabComparisonInsights.vue'

const opened = defineModel<boolean>({ default: false })
const props = defineProps<{ mechanism: LabKey; datasets: LabDataset[]; initialDatasetId: string | null }>()
const { t, locale } = useI18n()
interface Side { key: 'before' | 'after'; datasetId: string | null; runId: string | null; runs: LabRun[]; loading: boolean; error: string; generation: number }
const sides = reactive<Side[]>(['before', 'after'].map(key => ({ key: key as Side['key'], datasetId: null, runId: null, runs: [], loading: false, error: '', generation: 0 })))
const axis = ref<ComparisonAxis>('model'), result = ref<RunComparison | null>(null)
const filter = ref<ComparisonFilter>({ focus: 'all' })
const loading = ref(false), error = ref(''), offset = ref(0), limit = ref(50)
let generation = 0, controller: AbortController | undefined
const axes = computed(() => (['model', 'prompt', 'parameters'] as const).map(value => ({ value, label: t('evaluation.comparison.axes.' + value) })))
const ready = computed(() => sides.every(side => !side.loading && !side.error && side.runs.some(run => run.id === side.runId)) && sides[0]!.runId !== sides[1]!.runId)
const incomplete = computed(() => result.value && [result.value.left, result.value.right].some(run => run.status !== 'completed' || run.judged_cases < run.total_cases || run.completed_cases < run.total_cases))
const counts = computed(() => {
  const values = { increased: 0, decreased: 0, equal: 0, unknown: 0 }
  for (const item of result.value?.items ?? []) {
    if (item.pairing !== 'matched' || item.score_delta == null || !item.left_judgment || !item.right_judgment || item.left_error || item.right_error) values.unknown++
    else if (item.score_delta > 0) values.increased++
    else if (item.score_delta < 0) values.decreased++
    else values.equal++
  }
  return values
})
function number(value: number | null, digits: number) { return value == null ? '—' : value.toLocaleString(locale.value, { minimumFractionDigits: digits, maximumFractionDigits: digits }) }
function delta(value: number | null, digits: number) { return value == null ? '—' : (value > 0 ? '+' : '') + number(value, digits) }
function runLabel(run: LabRun) { return `${new Date(run.created_at).toLocaleString(locale.value)} · ${String(run.llm_snapshot.label ?? run.llm_snapshot.model ?? '—')} · ${t('evaluation.contract.status.' + run.status)} · ${run.id.slice(0, 8)}` }
function invalidate() { generation++; controller?.abort(); controller = undefined; result.value = null; error.value = ''; loading.value = false; offset.value = 0 }
async function loadRuns(side: Side) {
  const request = ++side.generation, mechanism = props.mechanism, dataset = side.datasetId
  side.runs = []; side.error = ''; side.loading = false
  if (!opened.value || !dataset) return
  side.loading = true
  try {
    const runs = await api.runs(mechanism, dataset)
    if (request === side.generation && opened.value && mechanism === props.mechanism && dataset === side.datasetId) side.runs = runs
  } catch (cause) { if (request === side.generation) side.error = apiErrorDetail(cause) ?? t('evaluation.comparison.loadError') }
  finally { if (request === side.generation) side.loading = false }
}
async function compare(pageOffset: number) {
  if (!ready.value) return
  invalidate()
  const request = generation
  controller = new AbortController(); loading.value = true
  try {
    const data = await api.compare(props.mechanism, sides[0]!.runId!, sides[1]!.runId!, axis.value, pageOffset, limit.value, controller.signal, filter.value)
    if (request === generation) { result.value = data; offset.value = pageOffset }
  } catch (cause) { if (request === generation) error.value = apiErrorDetail(cause) ?? t('evaluation.comparison.loadError') }
  finally { if (request === generation) loading.value = false }
}
async function swap() {
  const before = { dataset: sides[0]!.datasetId, run: sides[0]!.runId }, after = { dataset: sides[1]!.datasetId, run: sides[1]!.runId }
  sides[0]!.datasetId = after.dataset; sides[1]!.datasetId = before.dataset
  await nextTick()
  sides[0]!.runId = after.run; sides[1]!.runId = before.run
}
function chooseFocus(value: ComparisonFilter) { filter.value = value; void compare(0) }
for (const side of sides) watch(() => side.datasetId, () => { side.runId = null; void loadRuns(side) }, { flush: 'sync' })
watch(() => [opened.value, props.mechanism], () => {
  invalidate()
  for (const side of sides) {
    side.runId = null
    const dataset = opened.value ? props.initialDatasetId : null
    if (side.datasetId === dataset) void loadRuns(side)
    else side.datasetId = dataset
  }
}, { immediate: true, flush: 'sync' })
watch(() => [props.mechanism, opened.value, axis.value, ...sides.flatMap(side => [side.datasetId, side.runId])], () => { filter.value = { focus: 'all' }; invalidate() }, { flush: 'sync' })
watch(limit, () => { if (result.value) void compare(0) })
onBeforeUnmount(() => { invalidate(); for (const side of sides) side.generation++ })
</script>
<style scoped>
.comparison-dialog { width: 1200px; max-width: 96vw; }
.comparison-columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 24px; }
.comparison-columns section { min-width: 0; overflow-wrap: anywhere; }
h3, h4 { font-size: 1rem; line-height: 1.5; font-weight: 600; margin: 0 0 12px; }
.comparison-case { border: 1px solid v-bind('solaire.blue.accent'); border-radius: 8px; }
.comparison-notice { background: v-bind('solaire.orange.light'); }
.body--dark .comparison-notice { background: v-bind('solaire.orange.dark'); }
.comparison-error { color: v-bind('solaire.red.accent'); white-space: pre-wrap; overflow-wrap: anywhere; }
.page-size { min-width: 160px; }
@media (max-width: 1023px) { .comparison-columns { grid-template-columns: minmax(0, 1fr); } }
</style>
