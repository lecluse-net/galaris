<template>
<div>          <q-linear-progress v-if="loading" indeterminate color="primary" class="q-mb-md" />
          <q-banner v-if="error" role="alert" class="q-mb-md">
            {{ t('goal.loadErrors.cycles') }}
            <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="emit('retry')" /></template>
          </q-banner>
          <div v-if="!loading && !error && !cycles.length" class="text-grey-7 q-pa-lg text-center">
            {{ t('goal.noCycles') }}
          </div>
          <q-timeline
            v-else-if="cycles.length"
            class="goal-cycles-timeline"
            color="primary"
            layout="comfortable"
          >
            <q-timeline-entry
              v-for="cycle in cycles"
              :key="cycle.id"
              :title="t('goal.cycleNumber', { number: cycle.sequence })"
              :subtitle="formatDate(cycle.process_finished_at || cycle.task_finished_at || cycle.created_at)"
              :icon="cycle.verdict === 'STOP' ? 'stop_circle' : cycle.verdict === 'CONTINUE' ? 'play_circle' : 'hourglass_top'"
              :color="cycleColor(cycle)"
            >
              <div class="goal-cycle-mobile-date text-caption text-grey-7">
                {{ formatDate(cycle.process_finished_at || cycle.task_finished_at || cycle.created_at) }}
              </div>
              <q-card flat bordered>
                <q-card-section>
                  <div class="goal-cycle-heading row items-center q-gutter-sm q-mb-sm">
                    <q-chip dense outline :color="cycleColor(cycle)">
                      {{ cycle.verdict ? t('goal.cycleDecision', { decision: verdictLabel(cycle.verdict) }) : cycleStatusLabel(cycle.status) }}
                    </q-chip>
                    <span v-if="cycle.process_run_reference" class="text-caption">
                      {{ t('goal.cycleProcess.label') }}
                    </span>
                    <span v-else class="goal-cycle-costs text-caption text-grey-7">
                      {{ t('goal.taskCost') }} {{ formatCost(cycle.task_cost) }} ·
                      {{ t('goal.evaluationCost') }} {{ formatCost(cycle.judge_cost) }}
                    </span>
                    <q-space />
                    <GoalProcessRunButton v-if="cycle.process_run_reference" :run-reference="cycle.process_run_reference" :engine="cycle.process_run_engine" />
                    <q-btn
                      v-else-if="cycle.task_id && canViewTasks"
                      outline
                      color="primary"
                      icon="task_alt"
                      :label="t('goal.cycleTask', { number: cycle.sequence })"
                      @click="emit('openTask', cycle.task_id)"
                    />
                  </div>
                  <div v-if="cycle.verdict && !cycle.process_run_reference" class="text-caption text-grey-7 q-mb-sm">
                    {{ cycle.error ? t('goal.monitoringUnavailable') : cycle.judge_llm_id === null ? t('goal.monitoringNoDecision') : t('goal.monitoringRecorded') }}
                  </div>
                  <div v-if="cycle.progress_summary" class="q-mb-sm">
                    <div class="text-caption text-grey-7">{{ t('goal.progress') }}</div>
                    <div>{{ cycle.progress_summary }}</div>
                  </div>
                  <div v-if="cycle.reason" class="q-mb-sm">
                    <div class="text-caption text-grey-7">{{ t('goal.reason') }}</div>
                    <div>{{ cycle.reason }}</div>
                  </div>
                  <div v-if="cycle.evidence.length" class="q-mb-sm">
                    <div class="text-caption text-grey-7">{{ t('goal.evidence') }}</div>
                    <ul class="q-my-xs q-pl-lg">
                      <li v-for="evidence in cycle.evidence" :key="evidence">{{ evidence }}</li>
                    </ul>
                  </div>
                  <q-banner v-if="cycle.error" dense rounded class="goal-cycle-error bg-solaire-red-light text-negative">
                    {{ cycle.error }}
                  </q-banner>
                </q-card-section>
              </q-card>
            </q-timeline-entry>
          </q-timeline>
          <div
            v-if="total > 0"
            class="goal-cycle-pagination row items-center justify-between q-gutter-md q-mt-lg"
          >
            <div class="goal-cycle-page-size row items-center q-gutter-sm">
              <span class="text-caption text-grey-7">{{ t('goal.cyclePageSize') }}</span>
              <q-select
                :model-value="pageSize"
                :options="[10, 20, 50, 100, 500]"
                dense
                outlined
                style="width: 90px"
                @update:model-value="value => emit('pageSize', value)"
              />
              <span class="text-caption text-grey-7">
                {{ t('goal.cycleRange', {
                  from: cycleRangeStart,
                  to: cycleRangeEnd,
                  total: total,
                }) }}
              </span>
            </div>
            <q-pagination
              v-model="displayCyclePage"
              :max="pageCount"
              :max-pages="cyclePaginationMaxPages"
              direction-links
              boundary-links
              color="primary"
            />
          </div>

</div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import type { GoalCycle } from '../types'
import { useGoalFormatting } from '../presentation'
import GoalProcessRunButton from './GoalProcessRunButton.vue'
const { cycles, loading, error, total, page, pageSize, timezone, canViewTasks } = defineProps<{
  cycles: GoalCycle[]; loading: boolean; error: unknown; total: number; page: number; pageSize: number; timezone?: string; canViewTasks: boolean
}>()
const emit = defineEmits<{ retry: []; page: [value: number]; pageSize: [value: number | null]; openTask: [id: string] }>()
const { t } = useI18n(), $q = useQuasar()
const { formatCost, formatDate } = useGoalFormatting(() => timezone)
const displayCyclePage = computed({ get: () => page, set: value => emit('page', value) })
const pageCount = computed(() => Math.max(1, Math.ceil(total / pageSize)))
const cyclePaginationMaxPages = computed(() => $q.screen.lt.sm ? 3 : 7)
const cycleRangeStart = computed(() => total ? (page - 1) * pageSize + 1 : 0)
const cycleRangeEnd = computed(() => Math.min(page * pageSize, total))
function cycleStatusLabel(status: GoalCycle['status']): string {
  return t(`goal.cycleStatuses.${status}`)
}

function verdictLabel(verdict: NonNullable<GoalCycle['verdict']>): string {
  return t(`goal.verdicts.${verdict}`)
}

function cycleColor(cycle: GoalCycle): string {
  if (cycle.status === 'ERROR' || (cycle.process_run_reference && cycle.error)) return 'negative'
  if (cycle.verdict === 'STOP') return 'primary'
  if (cycle.verdict === 'CONTINUE') return 'positive'
  if (cycle.status === 'JUDGING') return 'secondary'
  return 'grey-7'
}


</script>
<style scoped>


.goal-cycle-heading,
.goal-cycle-pagination,
.goal-cycle-page-size {
  min-width: 0;
}

.goal-cycles-timeline,
.goal-cycles-timeline :deep(.q-timeline__entry),
.goal-cycles-timeline :deep(.q-timeline__content),
.goal-cycles-timeline :deep(.q-card),
.goal-cycle-costs {
  min-width: 0;
}

.goal-cycles-timeline :deep(.q-card),
.goal-cycle-pagination {
  width: 100%;
}

.goal-cycles-timeline :deep(.q-timeline__entry:last-child .q-timeline__dot::after) {
  content: "";
}

.goal-cycles-timeline :deep(.q-timeline__title),
.goal-cycles-timeline :deep(.q-timeline__subtitle),
.goal-cycle-costs,
.goal-cycle-error,
.goal-cycles-timeline li,
.goal-cycles-timeline .q-card-section > div {
  overflow-wrap: anywhere;
}

.goal-cycle-mobile-date {
  display: none;
}

@media (min-width: 1024px) {
  .goal-cycles-timeline :deep(.q-timeline__subtitle) {
    width: clamp(170px, 18vw, 220px);
    padding-right: 16px;
  }
}

@media (min-width: 1024px) {

  .goal-cycles-timeline :deep(.q-timeline__content) {
    padding-left: 16px;
  }
}

@media (max-width: 1023px) {

  .goal-cycles-timeline {
    display: block;
  }
}

@media (max-width: 1023px) {

  .goal-cycles-timeline :deep(.q-timeline__entry) {
    display: block;
    padding-left: 32px;
  }
}

@media (max-width: 1023px) {

  .goal-cycles-timeline :deep(.q-timeline__subtitle) {
    display: none;
  }
}

@media (max-width: 1023px) {

  .goal-cycles-timeline :deep(.q-timeline__dot) {
    position: absolute;
    min-width: 0;
  }
}

@media (max-width: 1023px) {

  .goal-cycles-timeline :deep(.q-timeline__content) {
    display: block;
    width: 100%;
    padding-top: 0;
    padding-left: 0;
  }
}

@media (max-width: 1023px) {

  .goal-cycle-mobile-date {
    display: block;
    margin-top: -8px;
    margin-bottom: 8px;
  }
}

@media (max-width: 599.98px) {

  .goal-cycle-heading,
.goal-cycle-pagination,
.goal-cycle-page-size {
    align-items: stretch;
    flex-direction: column;
  }

}

@media (max-width: 599.98px) {

  .goal-cycle-heading,
.goal-cycle-pagination {
    gap: 8px;
  }

}

@media (max-width: 599.98px) {

  .goal-cycle-heading .q-btn {
    width: 100%;
  }

}

@media (max-width: 599.98px) {

  .goal-cycle-heading .q-space {
    display: none;
  }

}

@media (max-width: 599.98px) {

  .goal-cycle-heading > * {
    margin: 0;
  }

}

@media (max-width: 599.98px) {

  .goal-cycle-page-size {
    gap: 4px;
  }

}

@media (max-width: 599.98px) {

  .goal-cycle-pagination :deep(.q-pagination) {
    align-self: center;
    max-width: 100%;
  }

}
</style>
