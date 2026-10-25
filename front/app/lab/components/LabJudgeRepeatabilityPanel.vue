<template>
  <section class="repeatability q-my-md" :aria-label="t('evaluation.repeatability.title')" :aria-busy="loading">
    <div class="row items-center justify-between q-gutter-sm q-mb-sm">
      <h3>{{ t('evaluation.repeatability.title') }}</h3>
      <q-btn outline color="primary" icon="refresh" :label="t(error ? 'evaluation.comparison.retry' : 'evaluation.repeatability.refresh')" :loading="loading" @click="load" />
    </div>
    <p>{{ t('evaluation.repeatability.help') }}</p>
    <p v-if="loading" role="status">{{ t('evaluation.repeatability.loading') }}</p>
    <p v-else-if="error" role="alert">{{ t('evaluation.repeatability.loadError') }}</p>
    <template v-else-if="report">
      <p v-if="!report.groups.length" role="status">{{ t('evaluation.repeatability.empty') }}</p>
      <div v-if="report.unqualified_campaign_ids.length" class="notice q-pa-md q-mb-md" role="status">
        <p>{{ t('evaluation.repeatability.unqualified', { count: report.unqualified_campaign_ids.length }) }}</p>
        <q-expansion-item :label="t('evaluation.repeatability.excludedCampaigns')">
          <ul><li v-for="id in report.unqualified_campaign_ids" :key="id">{{ id }}</li></ul>
        </q-expansion-item>
      </div>
      <section v-for="(group, index) in report.groups" :key="group.configuration_digest" class="configuration q-pa-md q-mb-md">
        <h4>{{ t('evaluation.repeatability.group', { number: index + 1, judge: judgeLabel(group) }) }}</h4>
        <p>{{ t('evaluation.repeatability.scope', { campaigns: group.campaign_ids.length, outputs: group.outputs }) }}</p>
        <p>{{ t('evaluation.repeatability.coverage', { usable: group.usable_judgments, expected: group.expected_judgments, missing: group.missing_judgments, invalid: group.unusable_judgments }) }}</p>
        <p>{{ t('evaluation.repeatability.pairs', { outputs: group.repeated_outputs, pairs: group.judgment_pairs }) }}</p>
        <p v-if="!group.repeated_outputs" class="notice q-pa-sm" role="status">{{ t('evaluation.repeatability.notMeasured') }}</p>
        <div v-else class="metrics">
          <section>
            <h5>{{ t('evaluation.repeatability.scoreDifference') }}</h5>
            <LabCaseEstimate :value="group.absolute_score_difference" />
          </section>
          <section>
            <h5>{{ t('evaluation.repeatability.verdictDisagreement') }}</h5>
            <LabCaseEstimate :value="group.verdict_disagreement_percent" />
          </section>
        </div>
        <q-expansion-item :label="t('evaluation.repeatability.sources')">
          <div class="q-pa-sm">
            <p>{{ t('evaluation.repeatability.digest', { digest: group.configuration_digest }) }}</p>
            <p>{{ t('evaluation.contract.campaigns') }}</p>
            <ul><li v-for="id in group.campaign_ids" :key="id">{{ id }}</li></ul>
            <LabReadableValue :value="group.configuration" />
          </div>
        </q-expansion-item>
      </section>
      <p v-if="['queued', 'running'].includes(run.status)" role="status">{{ t('evaluation.repeatability.active') }}</p>
      <p>{{ t('evaluation.repeatability.limits') }}</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { labWorkbenchService, type JudgeRepeatabilityGroup, type JudgeRepeatabilityReport, type LabKey, type LabRun } from '../services/labWorkbenchService'
import LabCaseEstimate from './LabCaseEstimate.vue'
import LabReadableValue from './LabReadableValue.vue'

const { mechanism, run } = defineProps<{ mechanism: LabKey; run: LabRun }>()
const { t } = useI18n()
const report = shallowRef<JudgeRepeatabilityReport | null>(null)
const loading = ref(false)
const error = ref(false)
let request = 0
let controller: AbortController | undefined

async function load() {
  const current = ++request, key = mechanism, id = run.id
  controller?.abort()
  controller = new AbortController()
  report.value = null
  error.value = false
  loading.value = true
  try {
    const value = await labWorkbenchService.judgeRepeatability(key, id, controller.signal)
    if (current === request && key === mechanism && id === run.id) report.value = value
  } catch {
    if (current === request && key === mechanism && id === run.id) error.value = true
  } finally {
    if (current === request) loading.value = false
  }
}

watch([() => mechanism, () => run.id, () => run.status, () => run.judged_cases,
  () => run.campaigns.map(campaign => `${campaign.id}:${campaign.status}:${campaign.results.length}`).join('|')], load, { immediate: true })
onBeforeUnmount(() => { request++; controller?.abort() })

function judgeLabel(group: JudgeRepeatabilityGroup) {
  const model = group.configuration.model
  if (model && typeof model === 'object') {
    if ('label' in model && typeof model.label === 'string' && model.label) return model.label
    if ('code' in model && typeof model.code === 'string' && model.code) return model.code
  }
  return t('evaluation.contract.judge')
}
</script>

<style scoped>
h3, h4, h5 { font-size: 1rem; line-height: 1.5; font-weight: 600; margin: 0 0 12px; }
h3 { font-size: 1.2rem; margin: 0; }
.repeatability { overflow-wrap: anywhere; }
.configuration { border: 1px solid var(--solaire-gray-accent); border-radius: 8px; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 24px; }
.notice { border-radius: 8px; background: var(--solaire-orange-light); }
.body--dark .notice { background: var(--solaire-orange-dark); }
</style>
