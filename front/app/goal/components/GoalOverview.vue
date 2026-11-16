<template>
  <div class="goal-overview-toolbar">
    <div class="goal-overview-identities">
      <div class="goal-overview-identity">
        <AgentAvatar :agent-id="goal.agent_id" :name="goal.agent_name" :has-avatar="hasAvatar" size="38px" />
        <div>
          <div class="text-caption text-grey-7">{{ t('goal.agent') }}</div>
          <div class="text-weight-medium">
            {{ goal.agent_name || goal.agent_code }}
          </div>
        </div>
      </div>
      <q-separator vertical class="gt-xs" />
      <div class="goal-overview-identity">
        <q-avatar icon="person" color="secondary" text-color="white" size="38px" />
        <div>
          <div class="text-caption text-grey-7">{{ t('goal.referrer') }}</div>
          <div class="text-weight-medium">
            {{ goal.referrer?.display_name || t('goal.referrerMissing') }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="canEdit" class="goal-overview-actions">
      <span v-if="goal.status !== 'COMPLETED'" class="inline-block">
        <q-btn
          unelevated
          color="positive"
          icon="rocket_launch"
          :label="t('goal.runNow')"
          :loading="commandPending"
          :disable="Boolean(goal.current_task_id)"
          @click="emit('command', 'runNow')"
        />
        <q-tooltip>
          {{ goal.current_task_id
            ? t('goal.runNowUnavailable')
            : t('goal.runNowHint') }}
        </q-tooltip>
      </span>
      <q-btn
        v-else
        unelevated
        color="positive"
        icon="replay"
        :label="t('goal.restart')"
        :loading="commandPending"
        @click="emit('command', 'resume')"
      />
      <q-btn
        v-if="goal.status === 'ACTIVE'"
        outline
        color="warning"
        icon="pause"
        :label="t('goal.pause')"
        :loading="commandPending"
        @click="emit('command', 'pause')"
      />
      <q-btn
        v-if="
          goal.status !== 'ACTIVE'
            && goal.status !== 'COMPLETED'
        "
        outline
        color="positive"
        icon="play_arrow"
        :label="goal.status === 'ERROR'
          ? t('goal.retry')
          : t('goal.resume')"
        :loading="commandPending"
        @click="emit('command', 'resume')"
      />
      <q-btn
        v-if="goal.status !== 'COMPLETED'"
        outline
        color="warning"
        icon="stop_circle"
        :label="t('goal.complete')"
        @click="emit('complete')"
      />
      <q-btn

        color="negative"
        icon="delete"
        :label="t('goal.delete')"
        @click="emit('delete')"
      >
        <q-tooltip>{{ t('goal.delete') }}</q-tooltip>
      </q-btn>
    </div>
  </div>

  <q-banner v-if="goal.last_error" dense rounded class="bg-solaire-red-light text-negative q-mt-md">
    <template #avatar><q-icon name="error" /></template>
    {{ goal.last_error }}
  </q-banner>

  <q-banner
    v-if="goal.status === 'PAUSED' && goal.pause_reason === 'REFERRER_NO_RESPONSE'"
    dense
    rounded
    class="bg-solaire-orange-light text-warning q-mt-md"
  >
    <template #avatar><q-icon name="mark_unread_chat_alt" /></template>
    {{ t('goal.referrerNoResponsePaused', { count: goal.referrer_max_reminders }) }}
  </q-banner>

  <div class="goal-overview-layout q-mt-md">
    <main class="goal-overview-main">
      <section class="goal-overview-section goal-overview-description-section">
        <div class="goal-description-heading row items-center justify-between q-mb-md">
          <div class="goal-overview-section-title">
            <q-icon name="flag" color="primary" size="22px" />
            <span>{{ t('goal.description') }}</span>
          </div>
        </div>
        <RichText class="goal-description" :content="goal.description" />
      </section>

      <section class="goal-overview-section">
        <div class="goal-overview-section-title q-mb-md">
          <q-icon name="account_tree" color="secondary" size="22px" />
          <span>{{ t('goal.hierarchy') }}</span>
        </div>
        <q-list v-if="parent || children.length">
          <q-item
            v-if="parent"
            clickable
            @click="emit('openGoal', parent.id)"
          >
            <q-item-section avatar>
              <q-icon name="arrow_upward" color="primary" />
            </q-item-section>
            <q-item-section>
              <q-item-label caption>{{ t('goal.parentGoal') }}</q-item-label>
              <q-item-label class="text-primary">{{ parent.title }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-separator v-if="parent && children.length" />
          <div
            v-if="children.length"
            class="text-caption text-grey-7 q-px-md q-pt-md q-pb-xs"
          >
            {{ t('goal.subGoals') }}
          </div>
          <q-item
            v-for="subGoal in children"
            :key="subGoal.id"
            clickable
            :style="{
              paddingInlineStart: `${12 + Math.max(0, subGoal.depth - 1) * 20}px`,
            }"
            @click="emit('openGoal', subGoal.id)"
          >
            <q-item-section avatar>
              <q-icon name="subdirectory_arrow_right" color="secondary" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ subGoal.title }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-chip dense :color="statusColor(subGoal.status)" text-color="white">
                {{ statusLabel(subGoal.status) }}
              </q-chip>
            </q-item-section>
          </q-item>
        </q-list>
        <div v-else class="goal-overview-empty text-grey-7">
          <q-icon name="account_tree" size="24px" />
          <span>{{ t('goal.noRelatedGoals') }}</span>
        </div>
      </section>
    </main>

    <aside class="goal-overview-sidebar">
      <section class="goal-overview-section">
        <div class="goal-overview-section-title q-mb-sm">
          <q-icon name="tune" color="primary" size="22px" />
          <span>{{ t('goal.pilotage') }}</span>
        </div>
        <div class="goal-pilotage-list">
          <div class="goal-pilotage-item">
            <q-icon name="bolt" color="secondary" size="20px" />
            <div>
              <div class="text-caption text-grey-7">{{ t('goal.automaticTriggers') }}</div>
              <div v-if="goal.recurrence">{{ t("goal.agenda.trigger") }}</div>
              <div v-else-if="goal.cycle_delay_seconds !== null">
                {{ t('goal.temporalTrigger') }} · {{ formatDuration(goal.cycle_delay_seconds) }}
              </div>
              <div v-else-if="parentTitle">
                {{ t('goal.afterGoal', { title: parentTitle }) }}
              </div>
              <div v-else class="text-grey-7">{{ t('goal.manualOnly') }}</div>
            </div>
          </div>
          <div class="goal-pilotage-item">
            <q-icon name="event" color="primary" size="20px" />
            <div>
              <div class="text-caption text-grey-7">{{ t('goal.nextCycle') }}</div>
              <div>{{ formatDate(goal.next_cycle_at) }}</div>
              <q-badge v-if="goal.current_task_id" color="primary" outline>
                {{ t('goal.currentTask') }}
              </q-badge>
            </div>
          </div>
        </div>
      </section>

      <section class="goal-overview-section">
        <div class="goal-overview-section-title q-mb-sm">
          <q-icon name="bar_chart" color="secondary" size="22px" />
          <span>{{ t('goal.activity') }}</span>
        </div>
        <div class="goal-activity-grid">
          <div class="goal-activity-metric">
            <div class="text-h5 text-weight-medium">{{ goal.cycle_count }}</div>
            <div class="text-caption text-grey-7">{{ t('goal.cycles') }}</div>
          </div>
          <div class="goal-activity-metric">
            <div class="text-h6 text-weight-medium">{{ formatCost(goal.total_cost) }}</div>
            <div class="text-caption text-grey-7">{{ t('goal.totalCost') }}</div>
          </div>
          <div class="goal-activity-metric goal-activity-metric--wide">
            <div class="text-weight-medium">{{ formatDate(goal.last_task_finished_at) }}</div>
            <div class="text-caption text-grey-7">{{ t('goal.lastCycle') }}</div>
          </div>
        </div>
        <div class="goal-cost-breakdown text-caption text-grey-7">
          {{ t('goal.taskCost') }} {{ formatCost(goal.task_cost) }}
          · {{ t('goal.evaluationCost') }} {{ formatCost(goal.evaluation_cost) }}
        </div>
      </section>
    </aside>
  </div>

</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { RichText } from '@/core/util'
import { AgentAvatar } from '@/app/agent'
import type { Goal, GoalTreeNode, GoalStatus } from '../types'
import { useGoalFormatting, statusColor } from '../presentation'
const props = defineProps<{
  goal: Goal; parent: GoalTreeNode | null; children: (GoalTreeNode & { depth: number })[]
  canEdit: boolean; commandPending: boolean; hasAvatar: boolean; parentTitle: string | null
  timezone?: string
}>()
const emit = defineEmits<{
  command: [action: 'pause' | 'resume' | 'runNow']; complete: []; delete: []; openGoal: [id: string]
}>()
const { t } = useI18n()
const { formatCost, formatDate, formatDuration } = useGoalFormatting(() => props.timezone)
function statusLabel(status: GoalStatus): string { return t(`goal.statuses.${status}`) }
</script>
<style scoped>


.goal-description-heading {
  min-width: 0;
}

.goal-description {
  line-height: 1.45;
}

.goal-overview-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
  padding: 4px 0 16px;
  border-bottom: 1px solid rgb(0 0 0 / 10%);
}

.goal-overview-identities,
.goal-overview-identity,
.goal-overview-actions,
.goal-overview-section-title,
.goal-pilotage-item {
  display: flex;
  align-items: center;
}

.goal-overview-identities {
  min-width: 0;
  gap: 16px;
}

.goal-overview-identity {
  min-width: 0;
  gap: 10px;
}

.goal-overview-identity > div,
.goal-pilotage-item > div {
  min-width: 0;
  overflow-wrap: anywhere;
}

.goal-overview-identities .q-separator--vertical {
  height: 42px;
}

.goal-overview-actions {
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.goal-overview-layout {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(300px, 0.9fr);
  gap: 16px;
  align-items: start;
}

.goal-overview-main,
.goal-overview-sidebar {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 16px;
}

.goal-overview-sidebar {
  position: sticky;
  top: 0;
}

.goal-overview-section {
  min-width: 0;
  padding: 16px;
  border: 1px solid rgb(0 0 0 / 12%);
  border-radius: 12px;
}

:global(.body--dark) .goal-overview-toolbar {
  border-bottom-color: rgb(255 255 255 / 14%);
}

:global(.body--dark) .goal-overview-section {
  border-color: rgb(255 255 255 / 16%);
}

.goal-overview-description-section {
  min-height: 280px;
}

.goal-overview-section-title {
  gap: 8px;
  font-size: 1rem;
  font-weight: 500;
}

.goal-overview-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 72px;
  text-align: center;
}

.goal-pilotage-list {
  display: flex;
  flex-direction: column;
}

.goal-pilotage-item {
  gap: 10px;
  padding: 12px 0;
}

.goal-pilotage-item + .goal-pilotage-item {
  border-top: 1px solid rgb(0 0 0 / 8%);
}

:global(.body--dark) .goal-pilotage-item + .goal-pilotage-item {
  border-top-color: rgb(255 255 255 / 12%);
}

.goal-activity-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.goal-activity-metric {
  min-width: 0;
  padding: 10px;
  border-radius: 8px;
  background: var(--solaire-blue-light);
  overflow-wrap: anywhere;
}

:global(.body--dark) .goal-activity-metric {
  background: var(--solaire-blue-dark);
}

.goal-activity-metric--wide {
  grid-column: 1 / -1;
}

.goal-cost-breakdown {
  margin-top: 10px;
  overflow-wrap: anywhere;
}

@media (max-width: 1023px) {

  .goal-overview-toolbar {
    grid-template-columns: minmax(0, 1fr);
  }

  .goal-overview-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .goal-overview-layout {
    grid-template-columns: 1fr;
  }

  .goal-overview-sidebar {
    position: static;
  }
}

@media (max-width: 599.98px) {

  .goal-overview-toolbar {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .goal-overview-identities {
    align-items: stretch;
    flex-direction: column;
    gap: 12px;
  }

  .goal-overview-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }

  .goal-overview-actions > .q-btn,
.goal-overview-actions > .inline-block,
.goal-overview-actions > .inline-block > .q-btn {
    width: 100%;
  }

  .goal-description-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .goal-description-heading {
    gap: 8px;
  }

  .goal-description-heading .q-btn {
    width: 100%;
  }

  .goal-description-heading .q-space {
    display: none;
  }

  .goal-description-heading > * {
    margin: 0;
  }

  .goal-overview-section {
    padding: 12px;
  }

}
</style>
