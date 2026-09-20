<template>
  <q-dialog v-model="opened">
    <q-card class="review-dialog">
      <q-card-section class="galaris-dialog-title row items-center"><div class="text-h6">{{ t('evaluation.insights.review') }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section>
      <q-card-section>
        <q-banner v-if="error" role="alert">{{ error }}</q-banner>
        <q-spinner v-if="loading" />
        <template v-if="queue">
          <p>{{ t('evaluation.insights.blindHelp') }}</p>
          <p v-if="agreement.count">{{ t('evaluation.insights.agreement', agreement) }}</p>
          <p v-if="!queue.items.length">{{ t('evaluation.insights.noReviewItems') }}</p>
          <q-select v-model="itemId" :options="queue.items.map(row => ({ value: row.result_id, label: row.name + ' · ' + t('evaluation.insights.attempt', { number: row.repetition }) }))" emit-value map-options outlined :label="t('evaluation.insights.reviewItem')" />
          <template v-if="item">
            <div class="review-columns q-my-md">
              <section><h3>{{ t('evaluation.contract.effectiveInput') }}</h3><LabReadableValue :value="item.input" />
                <q-expansion-item :label="t('evaluation.contract.sharedParameters')"><LabReadableValue :value="queue.parameters" /></q-expansion-item>
                <q-expansion-item :label="t('evaluation.contract.reference')"><p>{{ t('evaluation.contract.referenceHelp') }}</p><LabReadableValue :value="item.reference" /></q-expansion-item>
              </section>
              <section><h3>{{ t('evaluation.contract.result') }}</h3><LabReadableValue :value="item.output" /></section>
            </div>
            <p>{{ t('evaluation.insights.anchors') }}</p>
            <div v-for="dimension in queue.rubric.dimensions" :key="dimension.code" class="q-mb-lg">
              <strong>{{ dimension.label }} · {{ dimension.weight_percent }} %</strong><p>{{ dimension.criteria }}</p>
              <template v-if="!item.assessment">
                <q-input v-model.number="scores[dimension.code]" type="number" min="0" max="100" outlined :label="t('evaluation.insights.humanScore', { name: dimension.label })" :readonly="!canEdit || saving" />
                <q-input v-model="notes[dimension.code]" outlined type="textarea" :rows="2" maxlength="1500" :label="t('evaluation.insights.assessment', { name: dimension.label })" :readonly="!canEdit || saving" class="q-mt-sm" />
              </template>
              <template v-else>
                <p>{{ t('evaluation.insights.dimensionComparison', { human: humanDimension(dimension.code)?.score_percent ?? '—', judge: judgeDimension(dimension.code)?.score_percent ?? '—', delta: dimensionDelta(dimension.code) }) }}</p>
                <p>{{ humanDimension(dimension.code)?.assessment }}</p><p>{{ judgeDimension(dimension.code)?.assessment }}</p>
              </template>
            </div>
            <template v-if="!item.assessment">
              <q-input v-model="explanation" outlined type="textarea" maxlength="4000" :label="t('evaluation.insights.reviewNotes')" :readonly="!canEdit || saving" />
              <q-input v-model="critical" outlined type="textarea" :rows="2" :label="t('evaluation.insights.humanCritical')" :readonly="!canEdit || saving" class="q-my-md" />
              <q-btn v-if="canEdit" color="primary" :label="t('evaluation.insights.submitReview')" :loading="saving" :disable="!valid" @click="submit" />
            </template>
            <template v-else>
              <q-banner>{{ t('evaluation.insights.comparison', { human: item.human_score?.toFixed(1) ?? '—', judge: item.judge?.score_percent?.toFixed(1) ?? '—' }) }}
                · {{ t('evaluation.contract.status.' + item.human_verdict) }} / {{ t('evaluation.contract.status.' + (item.judge?.verdict ?? 'inconclusive')) }}</q-banner>
              <p>{{ item.assessment.explanation }}</p>
              <p v-for="failure in item.assessment.critical_failures" :key="failure">{{ failure }}</p>
              <p>{{ item.judge?.output?.explanation }}</p>
              <p v-for="failure in item.judge?.output?.critical_failures" :key="failure">{{ failure }}</p>
            </template>
          </template>
        </template>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { labWorkbenchService as api, type LabKey, type ReviewQueue } from '../services/labWorkbenchService'
import LabReadableValue from './LabReadableValue.vue'
const opened = defineModel<boolean>({ default: false })
const { mechanism, runId, canEdit, campaignId } = defineProps<{ mechanism: LabKey; runId: string; canEdit: boolean; campaignId?: string }>()
const { t } = useI18n()
const queue = ref<ReviewQueue | null>(null), itemId = ref<string | null>(null)
const loading = ref(false), saving = ref(false), error = ref('')
const scores = ref<Record<string, number | null>>({}), notes = ref<Record<string, string>>({})
const explanation = ref(''), critical = ref('')
const item = computed(() => queue.value?.items.find(row => row.result_id === itemId.value))
const valid = computed(() => Boolean(queue.value && explanation.value.trim() && queue.value.rubric.dimensions.every(dim => typeof scores.value[dim.code] === 'number' && Number.isFinite(scores.value[dim.code]) && scores.value[dim.code]! >= 0 && scores.value[dim.code]! <= 100 && notes.value[dim.code]?.trim())))
const humanDimension = (code: string) => item.value?.assessment?.dimensions?.find(dim => dim.code === code)
const judgeDimension = (code: string) => item.value?.judge?.output?.dimensions?.find(dim => dim.code === code)
function dimensionDelta(code: string) { const human = humanDimension(code), judge = judgeDimension(code); return human && judge ? (judge.score_percent - human.score_percent).toFixed(1) : '—' }
const agreement = computed(() => {
  const pairs = queue.value?.items.filter(row => row.human_score != null && row.judge?.score_percent != null) ?? []
  return { count: pairs.length, disagreements: pairs.filter(row => row.human_verdict !== row.judge?.verdict).length,
    error: pairs.length ? (pairs.reduce((sum, row) => sum + Math.abs(row.human_score! - row.judge!.score_percent!), 0) / pairs.length).toFixed(1) : '—' }
})
watch(itemId, () => { scores.value = {}; notes.value = {}; explanation.value = ''; critical.value = '' })
watch(() => [opened.value, runId, mechanism, campaignId] as const, async ([open, id, key, campaign], _, onCleanup) => {
  let stale = false; onCleanup(() => { stale = true })
  if (!open) return
  queue.value = null; itemId.value = null; loading.value = true; error.value = ''
  try { const value = await api.review(key, id, campaign); if (!stale) { queue.value = value; itemId.value = value.items.find(row => !row.assessment)?.result_id ?? value.items[0]?.result_id ?? null } }
  catch (reason) { if (!stale) error.value = apiErrorDetail(reason) ?? String(reason) }
  finally { if (!stale) loading.value = false }
}, { immediate: true })
async function submit() {
  if (!queue.value || !item.value || !valid.value || saving.value) return
  saving.value = true; error.value = ''
  const id = runId, key = mechanism, campaign = queue.value.campaign_id
  try {
    const value = await api.submitReview(key, id, { campaign_id: campaign, result_id: item.value.result_id,
      dimensions: queue.value.rubric.dimensions.map(dim => ({ code: dim.code, score_percent: scores.value[dim.code]!, assessment: notes.value[dim.code]!.trim() })),
      explanation: explanation.value.trim(), critical_failures: critical.value.split('\n').map(line => line.trim()).filter(Boolean),
    })
    if (id === runId && key === mechanism && queue.value?.campaign_id === campaign) queue.value = value
  } catch (reason) { error.value = apiErrorDetail(reason) ?? String(reason) }
  finally { saving.value = false }
}
</script>
<style scoped>
.review-dialog { width: 1100px; max-width: 96vw; }
.review-columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 24px; }
h3 { font-size: 1rem; font-weight: 600; }
</style>
