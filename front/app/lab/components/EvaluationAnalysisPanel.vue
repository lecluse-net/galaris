<template>
  <q-card v-if="analysis" flat bordered class="analysis-panel">
    <q-card-section>
      <div class="row items-start q-col-gutter-md">
        <div class="col">
          <div class="row items-center q-gutter-sm q-mb-sm">
            <q-icon name="psychology" color="deep-purple" size="md" />
            <div class="text-h6">{{ t('evaluation.analysisTitle') }}</div>
            <q-badge :color="verdictColor(analysis.verdict)" :label="t(`evaluation.verdict.${analysis.verdict}`)" />
            <q-badge outline color="deep-purple" :label="t('evaluation.confidence', { value: confidence })" />
          </div>
          <div class="text-body1">{{ analysis.summary }}</div>
        </div>
        <div class="text-caption text-grey-7 text-right">
          <div>{{ formatDate(analysis.created_at) }}</div>
          <div>{{ t('evaluation.taskRevision', { revision: analysis.task_revision }) }}</div>
          <div>{{ analysis.model }}</div>
          <div>{{ analysis.duration.toFixed(2) }} s · ${{ analysis.cost.toFixed(4) }}</div>
        </div>
      </div>
    </q-card-section>

    <q-separator />
    <q-card-section class="analysis-overview">
      <section>
        <div class="analysis-heading">{{ t('evaluation.goalAssessment') }}</div>
        <div>{{ analysis.goal_assessment }}</div>
      </section>
      <section>
        <div class="analysis-heading">{{ t('evaluation.observedOutcome') }}</div>
        <div>{{ analysis.observed_outcome }}</div>
      </section>
    </q-card-section>

    <q-card-section v-if="analysis.strengths.length" class="q-pt-none">
      <div class="analysis-heading">{{ t('evaluation.strengths') }}</div>
      <ul class="analysis-list">
        <li v-for="strength in analysis.strengths" :key="strength">{{ strength }}</li>
      </ul>
    </q-card-section>

    <q-card-section class="q-pt-none">
      <div class="analysis-heading">{{ t('evaluation.findings') }}</div>
      <q-list v-if="analysis.findings.length" bordered separator class="rounded-borders">
        <q-item v-for="finding in analysis.findings" :key="`${finding.title}:${finding.observation}`">
          <q-item-section>
            <q-item-label class="text-weight-medium">{{ finding.title }}</q-item-label>
            <q-item-label>{{ finding.observation }}</q-item-label>
            <q-item-label caption class="q-mt-xs">{{ finding.impact }}</q-item-label>
            <div v-if="finding.evidence.length" class="row q-gutter-xs q-mt-sm">
              <q-chip v-for="reference in finding.evidence" :key="reference" dense outline size="sm" icon="link">
                {{ reference }}
              </q-chip>
            </div>
          </q-item-section>
          <q-item-section side top>
            <q-badge :color="severityColor(finding.severity)" :label="t(`evaluation.severity.${finding.severity}`)" />
          </q-item-section>
        </q-item>
      </q-list>
      <div v-else class="text-grey-6">{{ t('evaluation.none') }}</div>
    </q-card-section>

    <q-card-section v-if="analysis.root_causes.length" class="q-pt-none">
      <div class="analysis-heading">{{ t('evaluation.rootCauses') }}</div>
      <q-list bordered separator class="rounded-borders">
        <q-item v-for="cause in analysis.root_causes" :key="cause.cause">
          <q-item-section>
            <q-item-label>{{ cause.cause }}</q-item-label>
            <q-item-label v-if="cause.evidence.length" caption>{{ cause.evidence.join(' · ') }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-circular-progress
              show-value
              :value="Math.round(cause.confidence * 100)"
              size="46px"
              :thickness="0.18"
              color="deep-purple"
              track-color="grey-3"
            >
              {{ Math.round(cause.confidence * 100) }}%
            </q-circular-progress>
          </q-item-section>
        </q-item>
      </q-list>
    </q-card-section>

    <q-card-section class="q-pt-none">
      <div class="analysis-heading">{{ t('evaluation.recommendations') }}</div>
      <q-list v-if="analysis.recommendations.length" bordered separator class="rounded-borders">
        <q-item v-for="item in analysis.recommendations" :key="`${item.scope}:${item.action}`">
          <q-item-section>
            <div class="row items-center q-gutter-xs q-mb-xs">
              <q-badge outline color="deep-purple" :label="t(`evaluation.scope.${item.scope}`)" />
              <q-item-label class="text-weight-medium">{{ item.action }}</q-item-label>
            </div>
            <q-item-label>{{ item.rationale }}</q-item-label>
            <q-item-label caption class="q-mt-xs">
              <strong>{{ t('evaluation.expectedImpact') }}:</strong> {{ item.expected_impact }}
            </q-item-label>
            <q-item-label caption>
              <strong>{{ t('evaluation.whereToChange') }}:</strong> {{ item.where_to_change }}
            </q-item-label>
            <div v-if="item.evidence.length" class="row q-gutter-xs q-mt-sm">
              <q-chip v-for="reference in item.evidence" :key="reference" dense outline size="sm" icon="link">
                {{ reference }}
              </q-chip>
            </div>
          </q-item-section>
          <q-item-section side top>
            <q-badge :color="priorityColor(item.priority)" :label="t(`evaluation.priority.${item.priority}`)" />
          </q-item-section>
        </q-item>
      </q-list>
      <div v-else class="text-grey-6">{{ t('evaluation.none') }}</div>
    </q-card-section>

    <q-card-section v-if="analysis.missing_evidence.length || analysis.next_questions.length" class="q-pt-none">
      <div class="analysis-overview">
        <section v-if="analysis.missing_evidence.length">
          <div class="analysis-heading">{{ t('evaluation.missingEvidence') }}</div>
          <ul class="analysis-list">
            <li v-for="item in analysis.missing_evidence" :key="item">{{ item }}</li>
          </ul>
        </section>
        <section v-if="analysis.next_questions.length">
          <div class="analysis-heading">{{ t('evaluation.nextQuestions') }}</div>
          <ul class="analysis-list">
            <li v-for="item in analysis.next_questions" :key="item">{{ item }}</li>
          </ul>
        </section>
      </div>
    </q-card-section>

    <q-separator />
    <q-card-section class="row items-center q-gutter-xs">
      <span class="text-caption text-grey-7 q-mr-xs">{{ t('evaluation.evidenceCoverage') }}</span>
      <q-chip dense icon="account_tree">{{ t('evaluation.coverage.tasks', { count: analysis.evidence.task_count }) }}</q-chip>
      <q-chip dense icon="history">{{ t('evaluation.coverage.attempts', { count: analysis.evidence.attempt_count }) }}</q-chip>
      <q-chip dense icon="forum">{{ t('evaluation.coverage.calls', { count: analysis.evidence.llm_call_count }) }}</q-chip>
      <q-chip dense icon="build">{{ t('evaluation.coverage.tools', { count: analysis.evidence.tool_call_count }) }}</q-chip>
      <q-chip dense icon="settings_suggest">{{ t('evaluation.coverage.processes', { count: analysis.evidence.process_run_count }) }}</q-chip>
      <q-chip v-if="analysis.evidence.truncated" dense color="warning" text-color="dark" icon="content_cut">
        {{ t('evaluation.coverage.truncated') }}
      </q-chip>
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type {
  AnalysisVerdict,
  FindingSeverity,
  RecommendationPriority,
  TaskAnalysis,
} from '../services/evaluationService'

const { analysis } = defineProps<{
  analysis: TaskAnalysis
}>()
const { t, locale } = useI18n()
const confidence = computed(() => `${Math.round(analysis.confidence * 100)}%`)

function verdictColor(verdict: AnalysisVerdict): string {
  return { success: 'positive', partial: 'orange', failure: 'negative', inconclusive: 'blue-grey' }[verdict]
}

function severityColor(severity: FindingSeverity): string {
  return {
    critical: 'negative',
    high: 'deep-orange',
    medium: 'orange',
    low: 'blue',
    info: 'blue-grey',
  }[severity]
}

function priorityColor(priority: RecommendationPriority): string {
  return { high: 'negative', medium: 'orange', low: 'blue-grey' }[priority]
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}
</script>

<style scoped>
.analysis-panel { border-left: 4px solid #673ab7; }
.analysis-overview { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
.analysis-heading { font-size: 0.875rem; font-weight: 600; color: #4527a0; margin-bottom: 8px; }
body.body--dark .analysis-heading { color: #b39ddb; }
.analysis-list { margin: 0; padding-left: 20px; }
.analysis-list li + li { margin-top: 6px; }
@media (max-width: 800px) { .analysis-overview { grid-template-columns: 1fr; } }
</style>
