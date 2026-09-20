<template>
  <q-page class="goal-page q-pa-md">
    <PageHeader help-key="goals" :help-text="$t('contextHelpPages.goals')" :icon="navigationIcon('flag_circle')" :title="t('nav.goal')" :description="t('nav.goal_desc')" />

    <div class="goal-page-heading row items-start justify-between q-mb-lg">
      <div class="text-body2 text-grey-7">{{ t('goal.subtitle') }}</div>
      <q-btn
        v-if="canEdit"
        color="primary"
        icon="add"
        :label="t('goal.new')"
        @click="openCreateDialog"
      />
    </div>

    <q-card
      flat
      bordered
      class="goal-runtime-card q-mb-md"
      :class="`goal-runtime-card--${runtimeColor}`"
    >
      <q-card-section v-if="store.settings" class="row items-center q-col-gutter-sm q-pa-sm">
        <div class="col-auto">
          <q-avatar :color="runtimeColor" text-color="white" :icon="runtimeIcon" size="36px" />
        </div>
        <div class="col">
          <div class="row items-center q-gutter-sm">
            <div class="text-subtitle1 text-weight-bold">{{ runtimeStatusLabel }}</div>
            <q-chip dense outline :color="runtimeColor" icon="schedule">
              {{ store.settings.timezone }}
            </q-chip>
            <q-chip dense outline color="primary" icon="calendar_month">
              {{ store.settings.schedule_enabled
                ? t('goal.runtime.globalScheduleEnabled')
                : t('goal.runtime.globalScheduleDisabled') }}
            </q-chip>
          </div>
          <div class="text-caption text-grey-7 q-mt-xs">{{ runtimeDescription }}</div>
        </div>
        <div
          v-if="canEdit && canManageAllAgents"
          class="goal-runtime-actions col-12 col-md-auto row q-gutter-sm"
        >
          <q-btn
            dense
            outline
            color="primary"
            icon="calendar_month"
            :label="t('goal.runtime.configureGlobalSchedule')"
            @click="openGlobalScheduleDialog"
          />
          <q-btn
            dense
            :color="store.settings.globally_paused ? 'positive' : 'negative'"
            :icon="store.settings.globally_paused ? 'play_circle' : 'pause_circle'"
            :label="store.settings.globally_paused
              ? t('goal.runtime.resumeAll')
              : t('goal.runtime.pauseAll')"
            :loading="store.settingsSaving"
            @click="toggleGlobalPause"
          />
        </div>
      </q-card-section>
      <q-card-section v-else class="row justify-center q-pa-lg">
        <q-spinner color="primary" size="32px" />
      </q-card-section>
    </q-card>

    <q-banner
      v-if="store.trackingLlmConfigured === false"
      rounded
      inline-actions
      class="goal-llm-banner bg-red-1 text-negative q-mb-lg"
    >
      <template #avatar>
        <q-icon name="warning_amber" size="42px" />
      </template>
      <div class="text-subtitle1 text-weight-bold">
        {{ t('goal.trackingLlmMissingTitle') }}
      </div>
      <div class="text-body2 q-mt-xs">
        {{ t('goal.trackingLlmMissingMessage') }}
      </div>
      <template #action>
        <q-btn
          v-if="canConfigureTrackingLlm"
          color="negative"
          icon="tune"
          :label="t('goal.trackingLlmMissingAction')"
          :to="{ path: '/llm', query: { tab: 'usage' } }"
        />
      </template>
    </q-banner>

    <div class="goal-summary-grid q-mb-lg">
      <div v-for="metric in metrics" :key="metric.key">
        <q-card flat bordered class="full-height goal-summary-metric-card">
          <q-card-section class="row items-center no-wrap">
            <q-avatar :color="metric.color" text-color="white" :icon="metric.icon" />
            <div class="col q-ml-md" style="min-width: 0">
              <div class="text-caption text-grey-7 ellipsis">{{ metric.label }}</div>
              <div class="text-h5 text-weight-medium">{{ metric.value }}</div>
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <q-card flat bordered class="q-mb-md">
      <q-card-section class="row q-col-gutter-md items-center">
        <div class="col-12 col-md-5">
          <q-input
            :model-value="store.search"
            outlined
            dense
            clearable
            debounce="300"
            :placeholder="t('goal.search')"
            @update:model-value="setSearch"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </div>
        <div class="col-12 col-sm-6 col-md-4">
          <AgentSelect
            :model-value="store.agentFilter"
            :options="agentOptions"
            outlined
            dense
            clearable
            emit-value
            map-options
            :label="t('goal.agent')"
            @update:model-value="setAgentFilter"
          />
        </div>
        <div class="col-12 col-sm-6 col-md-3">
          <q-select
            :model-value="store.statusFilter"
            :options="statusOptions"
            outlined
            dense
            clearable
            emit-value
            map-options
            :label="t('goal.status')"
            @update:model-value="setStatusFilter"
          />
        </div>
      </q-card-section>
    </q-card>

    <q-table
      flat
      bordered
      row-key="id"
      :rows="hierarchicalGoals"
      :columns="columns"
      :loading="store.loading"
      :pagination="{ rowsPerPage: 0 }"
      :grid="$q.screen.lt.md"
      hide-pagination
      class="goal-table"
      @row-click="(_, row) => openDetails(row)"
    >
      <template #item="props">
        <div class="q-table__grid-item col-12 goal-grid-item">
          <q-card
            flat
            bordered
            class="goal-mobile-card"
            role="button"
            tabindex="0"
            @click="openDetails(props.row)"
            @keydown.enter.self.prevent="openDetails(props.row)"
            @keydown.space.self.prevent="openDetails(props.row)"
          >
            <q-card-section class="q-pa-md">
              <div class="row items-start no-wrap q-gutter-sm">
                <div class="col goal-mobile-heading">
                  <div
                    class="text-subtitle1 text-weight-medium goal-mobile-title"
                    :style="goalIndentStyle(props.row.id)"
                  >
                    <q-icon
                      v-if="goalDepth(props.row.id) > 0"
                      name="subdirectory_arrow_right"
                      color="secondary"
                      class="q-mr-xs"
                    />
                    {{ props.row.title }}
                  </div>
                  <div class="text-caption text-grey-7 goal-mobile-description">
                    {{ props.row.description }}
                  </div>
                </div>
                <q-chip
                  dense
                  :color="statusColor(props.row.status)"
                  text-color="white"
                  :icon="statusIcon(props.row.status)"
                  class="q-ma-none"
                >
                  {{ statusLabel(props.row.status) }}
                </q-chip>
              </div>

              <div class="goal-mobile-metadata q-mt-md">
                <div>
                  <div class="goal-metadata-label">{{ t('goal.agent') }}</div>
                  <div class="ellipsis">{{ props.row.agent_name || props.row.agent_code }}</div>
                </div>
                <div>
                  <div class="goal-metadata-label">{{ t('goal.automaticTriggers') }}</div>
                  <div v-if="props.row.cycle_delay_seconds !== null" class="ellipsis">
                    <q-icon name="schedule" class="q-mr-xs" />
                    {{ formatDuration(props.row.cycle_delay_seconds) }}
                  </div>
                  <div v-if="parentGoalTitle(props.row)" class="ellipsis">
                    <q-icon name="account_tree" class="q-mr-xs" />
                    {{ t('goal.afterGoal', { title: parentGoalTitle(props.row) }) }}
                  </div>
                  <div
                    v-if="props.row.cycle_delay_seconds === null && !props.row.parent_goal_id"
                    class="text-grey-7"
                  >
                    {{ t('goal.manualOnly') }}
                  </div>
                </div>
                <div>
                  <div class="goal-metadata-label">{{ t('goal.nextCycle') }}</div>
                  <div>{{ formatDate(props.row.next_cycle_at) }}</div>
                </div>
                <div>
                  <div class="goal-metadata-label">{{ t('goal.cycles') }}</div>
                  <div>{{ props.row.cycle_count }} · {{ formatCost(props.row.total_cost) }}</div>
                </div>
              </div>

              <div v-if="props.row.last_error" class="text-caption text-negative q-mt-sm">
                {{ props.row.last_error }}
              </div>
            </q-card-section>

            <q-separator />
            <q-card-actions class="goal-list-actions" align="right" @click.stop>
              <q-btn
                flat
                round
                dense
                icon="visibility"
                color="primary"
                :aria-label="t('goal.details')"
                @click="openDetails(props.row)"
              >
                <q-tooltip>{{ t('goal.details') }}</q-tooltip>
              </q-btn>
              <q-btn
                v-if="canEdit"
                flat
                round
                dense
                icon="edit"
                color="primary"
                :aria-label="t('goal.editAction')"
                @click="openEdit(props.row)"
              >
                <q-tooltip>{{ t('goal.editAction') }}</q-tooltip>
              </q-btn>
              <span
                v-if="canEdit && props.row.status !== 'COMPLETED'"
                class="inline-block"
              >
                <q-btn
                  flat
                  round
                  dense
                  icon="rocket_launch"
                  color="positive"
                  :loading="commandGoalIds.has(props.row.id)"
                  :disable="Boolean(props.row.current_task_id)"
                  :aria-label="t('goal.runNow')"
                  @click="runCommand('runNow', props.row)"
                />
                <q-tooltip>
                  {{ props.row.current_task_id
                    ? t('goal.runNowUnavailable')
                    : t('goal.runNowHint') }}
                </q-tooltip>
              </span>
              <q-btn
                v-if="canEdit && props.row.status === 'ACTIVE'"
                flat
                round
                dense
                icon="pause"
                color="warning"
                :loading="commandGoalIds.has(props.row.id)"
                :aria-label="t('goal.pause')"
                @click="runCommand('pause', props.row)"
              >
                <q-tooltip>{{ t('goal.pause') }}</q-tooltip>
              </q-btn>
              <q-btn
                v-if="canEdit && props.row.status !== 'ACTIVE'"
                flat
                round
                dense
                :icon="props.row.status === 'COMPLETED' ? 'replay' : 'play_arrow'"
                color="positive"
                :loading="commandGoalIds.has(props.row.id)"
                :aria-label="props.row.status === 'COMPLETED'
                  ? t('goal.restart')
                  : props.row.status === 'ERROR'
                    ? t('goal.retry')
                    : t('goal.resume')"
                @click="runCommand('resume', props.row)"
              >
                <q-tooltip>
                  {{ props.row.status === 'COMPLETED'
                    ? t('goal.restart')
                    : props.row.status === 'ERROR'
                      ? t('goal.retry')
                      : t('goal.resume') }}
                </q-tooltip>
              </q-btn>
              <q-btn
                v-if="canEdit && props.row.status !== 'COMPLETED'"
                flat
                round
                dense
                icon="stop_circle"
                color="warning"
                :aria-label="t('goal.complete')"
                @click="confirmComplete(props.row)"
              >
                <q-tooltip>{{ t('goal.complete') }}</q-tooltip>
              </q-btn>
              <q-btn
                v-if="canEdit"
                flat
                round
                dense
                icon="delete"
                color="negative"
                :aria-label="t('goal.delete')"
                @click="confirmDelete(props.row)"
              >
                <q-tooltip>{{ t('goal.delete') }}</q-tooltip>
              </q-btn>
            </q-card-actions>
          </q-card>
        </div>
      </template>

      <template #body-cell-title="props">
        <q-td :props="props">
          <div :style="goalIndentStyle(props.row.id)">
            <div class="text-weight-medium">
              <q-icon
                v-if="goalDepth(props.row.id) > 0"
                name="subdirectory_arrow_right"
                color="secondary"
                class="q-mr-xs"
              />
              {{ props.row.title }}
            </div>
            <div class="text-caption text-grey-7 ellipsis-2-lines goal-description-cell">
              {{ props.row.description }}
            </div>
          </div>
        </q-td>
      </template>

      <template #body-cell-agent="props">
        <q-td :props="props">
          <div>{{ props.row.agent_name || props.row.agent_code }}</div>
          <div class="text-caption text-grey-7">@{{ props.row.agent_code }}</div>
        </q-td>
      </template>

      <template #body-cell-status="props">
        <q-td :props="props">
          <q-chip
            dense
            :color="statusColor(props.row.status)"
            text-color="white"
            :icon="statusIcon(props.row.status)"
          >
            {{ statusLabel(props.row.status) }}
          </q-chip>
          <div v-if="props.row.last_error" class="text-caption text-negative ellipsis goal-error-cell">
            {{ props.row.last_error }}
            <q-tooltip max-width="500px">{{ props.row.last_error }}</q-tooltip>
          </div>
        </q-td>
      </template>

      <template #body-cell-trigger="props">
        <q-td :props="props" class="goal-trigger-cell">
          <div v-if="props.row.cycle_delay_seconds !== null" class="ellipsis">
            <q-icon name="schedule" color="primary" class="q-mr-xs" />
            {{ formatDuration(props.row.cycle_delay_seconds) }}
          </div>
          <div v-if="parentGoalTitle(props.row)" class="ellipsis">
            <q-icon name="account_tree" color="secondary" class="q-mr-xs" />
            {{ t('goal.afterGoal', { title: parentGoalTitle(props.row) }) }}
          </div>
          <span
            v-if="props.row.cycle_delay_seconds === null && !props.row.parent_goal_id"
            class="text-caption text-grey-7"
          >
            {{ t('goal.manualOnly') }}
          </span>
        </q-td>
      </template>

      <template #body-cell-next_cycle_at="props">
        <q-td :props="props">
          <div>{{ formatDate(props.row.next_cycle_at) }}</div>
          <q-badge v-if="props.row.current_task_id" color="primary" outline>
            {{ t('goal.currentTask') }}
          </q-badge>
        </q-td>
      </template>

      <template #body-cell-cycles="props">
        <q-td :props="props">
          <div class="text-weight-medium">{{ props.row.cycle_count }}</div>
          <div class="text-caption text-grey-7">{{ formatCost(props.row.total_cost) }}</div>
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" class="goal-list-actions-cell" @click.stop>
          <div class="goal-list-actions">
            <q-btn
              flat
              round
              dense
              icon="visibility"
              color="primary"
              :aria-label="t('goal.details')"
              @click="openDetails(props.row)"
            >
              <q-tooltip>{{ t('goal.details') }}</q-tooltip>
            </q-btn>
            <q-btn
              v-if="canEdit"
              flat
              round
              dense
              icon="edit"
              color="primary"
              :aria-label="t('goal.editAction')"
              @click="openEdit(props.row)"
            >
              <q-tooltip>{{ t('goal.editAction') }}</q-tooltip>
            </q-btn>
            <span
              v-if="canEdit && props.row.status !== 'COMPLETED'"
              class="inline-block"
            >
              <q-btn
                flat
                round
                dense
                icon="rocket_launch"
                color="positive"
                :loading="commandGoalIds.has(props.row.id)"
                :disable="Boolean(props.row.current_task_id)"
                :aria-label="t('goal.runNow')"
                @click="runCommand('runNow', props.row)"
              />
              <q-tooltip>
                {{ props.row.current_task_id
                  ? t('goal.runNowUnavailable')
                  : t('goal.runNowHint') }}
              </q-tooltip>
            </span>
            <q-btn
              v-if="canEdit && props.row.status === 'ACTIVE'"
              flat
              round
              dense
              icon="pause"
              color="warning"
              :loading="commandGoalIds.has(props.row.id)"
              :aria-label="t('goal.pause')"
              @click="runCommand('pause', props.row)"
            >
              <q-tooltip>{{ t('goal.pause') }}</q-tooltip>
            </q-btn>
            <q-btn
              v-if="canEdit && props.row.status !== 'ACTIVE'"
              flat
              round
              dense
              :icon="props.row.status === 'COMPLETED' ? 'replay' : 'play_arrow'"
              color="positive"
              :loading="commandGoalIds.has(props.row.id)"
              :aria-label="props.row.status === 'COMPLETED'
                ? t('goal.restart')
                : props.row.status === 'ERROR'
                  ? t('goal.retry')
                  : t('goal.resume')"
              @click="runCommand('resume', props.row)"
            >
              <q-tooltip>
                {{ props.row.status === 'COMPLETED'
                  ? t('goal.restart')
                  : props.row.status === 'ERROR'
                    ? t('goal.retry')
                    : t('goal.resume') }}
              </q-tooltip>
            </q-btn>
            <q-btn
              v-if="canEdit && props.row.status !== 'COMPLETED'"
              flat
              round
              dense
              icon="stop_circle"
              color="warning"
              :aria-label="t('goal.complete')"
              @click="confirmComplete(props.row)"
            >
              <q-tooltip>{{ t('goal.complete') }}</q-tooltip>
            </q-btn>
            <q-btn
              v-if="canEdit"
              flat
              round
              dense
              icon="delete"
              color="negative"
              :aria-label="t('goal.delete')"
              @click="confirmDelete(props.row)"
            >
              <q-tooltip>{{ t('goal.delete') }}</q-tooltip>
            </q-btn>
          </div>
        </q-td>
      </template>

      <template #no-data>
        <div class="full-width row flex-center text-grey-7 q-pa-xl">
          <q-icon name="flag_circle" size="32px" class="q-mr-sm" />
          {{ t('goal.noGoals') }}
        </div>
      </template>
    </q-table>

    <div class="goal-pagination row items-center justify-between q-mt-md">
      <q-select
        :model-value="store.pageSize"
        :options="[10, 20, 50, 100, 500]"
        dense
        outlined
        style="width: 100px"
        @update:model-value="setPageSize"
      />
      <q-pagination
        v-model="displayPage"
        :max="store.pageCount"
        direction-links
        boundary-links
        color="primary"
      />
    </div>


    <q-dialog v-model="globalScheduleDialogOpen">
      <q-card class="goal-schedule-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center justify-between">
          <div class="text-h6">{{ t('goal.runtime.globalScheduleTitle') }}</div>
          <q-btn
            flat
            round
            dense
            icon="close"
            :aria-label="t('common.close')"
            v-close-popup
          />
        </q-card-section>
        <q-form class="goal-form" @submit="submitGlobalScheduleDialog">
          <q-card-section class="goal-form-content q-pa-lg scroll">
            <GoalScheduleEditor
              v-model:enabled="globalScheduleEnabledDraft"
              v-model:slots="globalScheduleDraft"
              scope="global"
            />
          </q-card-section>
          <q-separator />
          <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
            <q-btn flat :label="t('common.cancel')" v-close-popup />
            <q-btn
              color="primary"
              type="submit"
              :label="t('common.save')"
              :loading="store.settingsSaving"
              :disable="!canSaveGlobalSchedule"
            />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>

    <q-dialog
      v-model="goalDialogOpen"
      allow-focus-outside
      transition-show="slide-up"
      transition-hide="slide-down"
    >
      <q-card class="goal-detail-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="goal-detail-title col row items-center">
            <div class="text-h6">
              {{ goalDialogTitle || t('goal.new') }}
            </div>
            <q-chip
              v-if="editingGoal && store.currentGoal?.id === editingGoal.id"
              dense
              :color="statusColor(store.currentGoal.status)"
              text-color="white"
              :icon="statusIcon(store.currentGoal.status)"
            >
              {{ statusLabel(store.currentGoal.status) }}
            </q-chip>
          </div>
          <q-btn
            flat
            round
            dense
            icon="close"
            :aria-label="t('common.close')"
            v-close-popup
          />
        </q-card-section>
        <q-linear-progress v-if="store.detailLoading" indeterminate color="primary" />
        <q-tabs
          v-model="goalDialogTab"
          inline-label
          align="left"
          active-color="primary"
          indicator-color="primary"
          class="goal-dialog-tabs text-primary bg-grey-1"
        >
          <q-tab
            v-if="editingGoal"
            name="overview"
            icon="flag"
            :label="t('goal.tabs.overview')"
          />
          <q-tab
            v-if="canEdit"
            name="edit"
            icon="edit"
            :label="t('goal.tabs.edit')"
          />
          <q-tab
            v-if="editingGoal"
            name="tracking"
            icon="fact_check"
            :label="t('goal.tabs.tracking')"
          />
          <q-tab
            v-if="editingGoal"
            name="cycles"
            icon="autorenew"
            :label="t('goal.tabs.cycles')"
          />
        </q-tabs>
        <q-separator />
        <q-tab-panels v-model="goalDialogTab" animated class="goal-dialog-panels">
        <q-tab-panel
          v-if="store.currentGoal && editingGoal && store.currentGoal.id === editingGoal.id"
          name="overview"
          class="goal-overview-tab goal-detail-content"
        >
          <div class="goal-overview-toolbar">
            <div class="goal-overview-identities">
              <div class="goal-overview-identity">
                <q-avatar icon="smart_toy" color="primary" text-color="white" size="38px" />
                <div>
                  <div class="text-caption text-grey-7">{{ t('goal.agent') }}</div>
                  <div class="text-weight-medium">
                    {{ store.currentGoal.agent_name || store.currentGoal.agent_code }}
                  </div>
                  <div class="text-caption text-grey-7">@{{ store.currentGoal.agent_code }}</div>
                </div>
              </div>
              <q-separator vertical class="gt-xs" />
              <div class="goal-overview-identity">
                <q-avatar icon="person" color="secondary" text-color="white" size="38px" />
                <div>
                  <div class="text-caption text-grey-7">{{ t('goal.referrer') }}</div>
                  <div class="text-weight-medium">
                    {{ store.currentGoal.referrer?.display_name || t('goal.referrerMissing') }}
                  </div>
                </div>
              </div>
            </div>

            <div v-if="canEdit" class="goal-overview-actions">
              <span v-if="store.currentGoal.status !== 'COMPLETED'" class="inline-block">
                <q-btn
                  unelevated
                  color="positive"
                  icon="rocket_launch"
                  :label="t('goal.runNow')"
                  :loading="commandGoalIds.has(store.currentGoal.id)"
                  :disable="Boolean(store.currentGoal.current_task_id)"
                  @click="runCommand('runNow', store.currentGoal)"
                />
                <q-tooltip>
                  {{ store.currentGoal.current_task_id
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
                :loading="commandGoalIds.has(store.currentGoal.id)"
                @click="runCommand('resume', store.currentGoal)"
              />
              <q-btn
                v-if="store.currentGoal.status === 'ACTIVE'"
                outline
                color="warning"
                icon="pause"
                :label="t('goal.pause')"
                :loading="commandGoalIds.has(store.currentGoal.id)"
                @click="runCommand('pause', store.currentGoal)"
              />
              <q-btn
                v-if="
                  store.currentGoal.status !== 'ACTIVE'
                  && store.currentGoal.status !== 'COMPLETED'
                "
                outline
                color="positive"
                icon="play_arrow"
                :label="store.currentGoal.status === 'ERROR'
                  ? t('goal.retry')
                  : t('goal.resume')"
                :loading="commandGoalIds.has(store.currentGoal.id)"
                @click="runCommand('resume', store.currentGoal)"
              />
              <q-btn
                v-if="store.currentGoal.status !== 'COMPLETED'"
                outline
                color="warning"
                icon="stop_circle"
                :label="t('goal.complete')"
                @click="confirmComplete(store.currentGoal)"
              />
              <q-btn
                outline
                color="negative"
                icon="delete"
                :label="t('goal.delete')"
                @click="confirmDelete(store.currentGoal)"
              >
                <q-tooltip>{{ t('goal.delete') }}</q-tooltip>
              </q-btn>
            </div>
          </div>

          <q-banner v-if="store.currentGoal.last_error" dense rounded class="bg-red-1 text-negative q-mt-md">
            <template #avatar><q-icon name="error" /></template>
            {{ store.currentGoal.last_error }}
          </q-banner>

          <q-banner
            v-if="store.currentGoal.status === 'PAUSED' && store.currentGoal.pause_reason === 'REFERRER_NO_RESPONSE'"
            dense
            rounded
            class="bg-orange-1 text-warning q-mt-md"
          >
            <template #avatar><q-icon name="mark_unread_chat_alt" /></template>
            {{ t('goal.referrerNoResponsePaused', { count: store.currentGoal.referrer_max_reminders }) }}
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
                <RichText class="goal-description" :content="store.currentGoal.description" />
              </section>

              <section class="goal-overview-section">
                <div class="goal-overview-section-title q-mb-md">
                  <q-icon name="account_tree" color="secondary" size="22px" />
                  <span>{{ t('goal.hierarchy') }}</span>
                </div>
                <q-list v-if="currentParentNode || currentSubGoalRows.length">
                  <q-item
                    v-if="currentParentNode"
                    clickable
                    @click="openGoalDetailsById(currentParentNode.id)"
                  >
                    <q-item-section avatar>
                      <q-icon name="arrow_upward" color="primary" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label caption>{{ t('goal.parentGoal') }}</q-item-label>
                      <q-item-label class="text-primary">{{ currentParentNode.title }}</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-separator v-if="currentParentNode && currentSubGoalRows.length" />
                  <div
                    v-if="currentSubGoalRows.length"
                    class="text-caption text-grey-7 q-px-md q-pt-md q-pb-xs"
                  >
                    {{ t('goal.subGoals') }}
                  </div>
                  <q-item
                    v-for="subGoal in currentSubGoalRows"
                    :key="subGoal.id"
                    clickable
                    :style="{
                      paddingInlineStart: `${12 + Math.max(0, subGoal.depth - 1) * 20}px`,
                    }"
                    @click="openGoalDetailsById(subGoal.id)"
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
                      <div v-if="store.currentGoal.cycle_delay_seconds !== null">
                        {{ t('goal.temporalTrigger') }} · {{ formatDuration(store.currentGoal.cycle_delay_seconds) }}
                      </div>
                      <div v-else-if="parentGoalTitle(store.currentGoal)">
                        {{ t('goal.afterGoal', { title: parentGoalTitle(store.currentGoal) }) }}
                      </div>
                      <div v-else class="text-grey-7">{{ t('goal.manualOnly') }}</div>
                    </div>
                  </div>
                  <div class="goal-pilotage-item">
                    <q-icon name="event" color="primary" size="20px" />
                    <div>
                      <div class="text-caption text-grey-7">{{ t('goal.nextCycle') }}</div>
                      <div>{{ formatDate(store.currentGoal.next_cycle_at) }}</div>
                      <q-badge v-if="store.currentGoal.current_task_id" color="primary" outline>
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
                    <div class="text-h5 text-weight-medium">{{ store.currentGoal.cycle_count }}</div>
                    <div class="text-caption text-grey-7">{{ t('goal.cycles') }}</div>
                  </div>
                  <div class="goal-activity-metric">
                    <div class="text-h6 text-weight-medium">{{ formatCost(store.currentGoal.total_cost) }}</div>
                    <div class="text-caption text-grey-7">{{ t('goal.totalCost') }}</div>
                  </div>
                  <div class="goal-activity-metric goal-activity-metric--wide">
                    <div class="text-weight-medium">{{ formatDate(store.currentGoal.last_task_finished_at) }}</div>
                    <div class="text-caption text-grey-7">{{ t('goal.lastCycle') }}</div>
                  </div>
                </div>
                <div class="goal-cost-breakdown text-caption text-grey-7">
                  {{ t('goal.taskCost') }} {{ formatCost(store.currentGoal.task_cost) }}
                  · {{ t('goal.evaluationCost') }} {{ formatCost(store.currentGoal.evaluation_cost) }}
                </div>
              </section>
            </aside>
          </div>

        </q-tab-panel>
        <q-tab-panel
          v-if="store.currentGoal && editingGoal && store.currentGoal.id === editingGoal.id"
          name="tracking"
          class="goal-tracking-tab q-pa-none"
        >
          <div class="goal-tracking-document-editor">
            <WorkingDocumentEditor
              :key="`${store.currentGoal.agent_id}:${store.currentGoal.tracking_document_id}`"
              :document-id="store.currentGoal.tracking_document_id"
              :agent-id="store.currentGoal.agent_id"
              :editable="canEdit"
              content-min-height="min(48vh, 480px)"
              content-max-height="55vh"
            />
          </div>
        </q-tab-panel>
        <q-tab-panel
          v-if="store.currentGoal && editingGoal && store.currentGoal.id === editingGoal.id"
          name="cycles"
          class="goal-detail-content"
        >
          <q-linear-progress v-if="store.cyclesLoading" indeterminate color="primary" class="q-mb-md" />
          <div v-if="!store.cyclesLoading && !store.cycles.length" class="text-grey-7 q-pa-lg text-center">
            {{ t('goal.noCycles') }}
          </div>
          <q-timeline
            v-else-if="store.cycles.length"
            class="goal-cycles-timeline"
            color="primary"
            layout="comfortable"
          >
            <q-timeline-entry
              v-for="cycle in store.cycles"
              :key="cycle.id"
              :title="t('goal.cycleNumber', { number: cycle.sequence })"
              :subtitle="formatDate(cycle.task_finished_at || cycle.created_at)"
              :icon="cycle.verdict === 'STOP' ? 'stop_circle' : cycle.verdict === 'CONTINUE' ? 'play_circle' : 'hourglass_top'"
              :color="cycleColor(cycle)"
            >
              <div class="goal-cycle-mobile-date text-caption text-grey-7">
                {{ formatDate(cycle.task_finished_at || cycle.created_at) }}
              </div>
              <q-card flat bordered>
                <q-card-section>
                  <div class="goal-cycle-heading row items-center q-gutter-sm q-mb-sm">
                    <q-chip dense outline :color="cycleColor(cycle)">
                      {{ cycle.verdict ? verdictLabel(cycle.verdict) : cycleStatusLabel(cycle.status) }}
                    </q-chip>
                    <span class="goal-cycle-costs text-caption text-grey-7">
                      {{ t('goal.taskCost') }} {{ formatCost(cycle.task_cost) }} ·
                      {{ t('goal.evaluationCost') }} {{ formatCost(cycle.judge_cost) }}
                    </span>
                    <q-space />
                    <q-btn
                      v-if="cycle.task_id && canViewTasks"
                      flat
                      color="primary"
                      icon="open_in_new"
                      :label="cycle.task_label || t('goal.task')"
                      @click="openTask(cycle.task_id)"
                    />
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
                  <q-banner v-if="cycle.error" dense rounded class="goal-cycle-error bg-red-1 text-negative">
                    {{ cycle.error }}
                  </q-banner>
                </q-card-section>
              </q-card>
            </q-timeline-entry>
          </q-timeline>
          <div
            v-if="store.cycleTotal > 0"
            class="goal-cycle-pagination row items-center justify-between q-gutter-md q-mt-lg"
          >
            <div class="goal-cycle-page-size row items-center q-gutter-sm">
              <span class="text-caption text-grey-7">{{ t('goal.cyclePageSize') }}</span>
              <q-select
                :model-value="store.cyclePageSize"
                :options="[10, 20, 50, 100, 500]"
                dense
                outlined
                style="width: 90px"
                @update:model-value="setCyclePageSize"
              />
              <span class="text-caption text-grey-7">
                {{ t('goal.cycleRange', {
                  from: cycleRangeStart,
                  to: cycleRangeEnd,
                  total: store.cycleTotal,
                }) }}
              </span>
            </div>
            <q-pagination
              v-model="displayCyclePage"
              :max="store.cyclePageCount"
              :max-pages="cyclePaginationMaxPages"
              direction-links
              boundary-links
              color="primary"
            />
          </div>
        </q-tab-panel>
        <q-tab-panel v-if="canEdit" name="edit" class="goal-edit-tab q-pa-none">
          <q-form class="goal-form" @submit="submitForm">
            <q-card-section class="goal-form-content goal-edit-grid q-pa-sm scroll">
              <q-card flat class="goal-edit-primary-card">
                <q-card-section class="q-pa-sm q-gutter-sm">
                  <q-input
                    v-model="form.title"
                    dense
                    outlined
                    hide-bottom-space
                    :label="t('goal.title')"
                    :rules="[requiredRule]"
                  />
                  <div>
                    <div class="text-subtitle2 q-mb-xs">
                      {{ t('goal.description') }} <span class="text-negative">*</span>
                    </div>
                    <RichTextEditor
                      v-model="form.description"
                      min-height="301px"
                      max-height="45vh"
                      :aria-label="t('goal.description')"
                    />
                    <div class="text-caption text-grey-7 q-mt-xs">
                      {{ t('goal.descriptionHtmlHint') }}
                    </div>
                  </div>
                </q-card-section>
              </q-card>
              <div class="goal-edit-sidebar">
                <q-card flat class="goal-referrer-section">
                  <q-card-section class="q-pa-sm">
                    <div class="goal-role-legend row items-center q-gutter-xs text-primary">
                      <q-icon name="smart_toy" size="18px" />
                      <span class="text-subtitle2">{{ t('goal.workerLegend') }}</span>
                    </div>
                    <AgentSelect
                      :model-value="form.agentId"
                      :options="agentOptions"
                      dense
                      outlined
                      hide-bottom-space
                      emit-value
                      map-options
                      :label="t('goal.agent')"
                      :rules="[requiredRule]"
                      :disable="Boolean(editingGoal?.cycle_count)"
                      @update:model-value="setOwnerAgent"
                    />
                    <div
                      class="goal-role-legend goal-role-legend--spaced row items-center q-gutter-xs text-primary"
                    >
                      <q-icon name="supervisor_account" size="18px" />
                      <span class="text-subtitle2">{{ t('goal.supervisorLegend') }}</span>
                    </div>
                    <div class="row q-col-gutter-sm items-start">
                      <div class="col">
                        <q-select
                          v-model="form.messengerReferrer"
                          :options="messengerReferrerOptions"
                          :option-label="messengerOptionLabel"
                          dense
                          outlined
                          hide-bottom-space
                          clearable
                          use-input
                          input-debounce="300"
                          :label="t('goal.referrerContact')"
                          :loading="messengerSearching"
                          :rules="[requiredRule]"
                          @filter="filterMessengerReferrers"
                          @filter-abort="invalidateMessengerSearch"
                          @popup-hide="invalidateMessengerSearch"
                        >
                          <template #no-option>
                            <q-item>
                              <q-item-section class="text-grey-7">
                                {{ t(form.agentId ? 'goal.referrerNoContact' : 'goal.referrerSelectAgent') }}
                              </q-item-section>
                            </q-item>
                          </template>
                        </q-select>
                      </div>
                      <div class="col-auto">
                        <q-btn
                          no-caps
                          icon="person"
                          :outline="!form.messengerReferrer?.is_current_user"
                          :unelevated="Boolean(form.messengerReferrer?.is_current_user)"
                          color="primary"
                          :label="t('goal.referrerMe')"
                          :loading="messengerSearching"
                          @click="selectCurrentUserReferrer()"
                        />
                      </div>
                    </div>
                    <div class="goal-referrer-reminders">
                      <q-input
                        v-model.number="form.referrerMaxReminders"
                        dense
                        outlined
                        hide-bottom-space
                        type="number"
                        min="0"
                        step="1"
                        class="goal-referrer-reminders-control"
                        :aria-label="t('goal.referrerMaxReminders')"
                        :rules="[nonNegativeIntegerRule]"
                      />
                      <div class="goal-referrer-reminders-hint text-caption text-grey-7">
                        {{ t('goal.referrerMaxRemindersHint') }}
                      </div>
                    </div>
                  </q-card-section>
                </q-card>
                <q-card flat class="goal-trigger-section">
                  <q-card-section class="q-pa-sm">
                    <div class="goal-role-legend row items-center q-gutter-xs text-primary">
                      <q-icon name="bolt" size="18px" />
                      <span class="text-subtitle2">{{ t('goal.automaticTriggers') }}</span>
                    </div>
                    <q-option-group
                      :model-value="form.triggerMode"
                      :options="triggerModeOptions"
                      color="primary"
                      type="radio"
                      dense
                      class="goal-trigger-options"
                      @update:model-value="setGoalTriggerMode"
                    />
                    <div v-if="form.triggerMode !== 'RELATIONAL'" class="q-mt-sm">
                      <div class="text-subtitle2 q-mb-xs">{{ t('goal.frequency') }}</div>
                      <div class="row q-col-gutter-sm">
                        <div class="col">
                          <q-input
                            v-model.number="form.delayValue"
                            dense
                            outlined
                            hide-bottom-space
                            type="number"
                            min="0"
                            step="1"
                            :rules="[nonNegativeRule]"
                          />
                        </div>
                        <div class="col-5">
                          <q-select
                            v-model="form.delayUnit"
                            :options="durationUnitOptions"
                            dense
                            outlined
                            emit-value
                            map-options
                          />
                        </div>
                      </div>
                      <div class="text-caption text-grey-7">{{ t('goal.frequencyHint') }}</div>
                      <q-banner
                        v-if="form.triggerMode === 'TEMPORAL_DEFAULT'"
                        dense
                        rounded
                        class="bg-grey-2 text-grey-9 q-mt-sm"
                      >
                        <template #avatar><q-icon name="event_available" /></template>
                        {{ t('goal.runtime.defaultScheduleHint') }}
                      </q-banner>
                    </div>
                    <q-select
                      v-else
                      v-model="form.parentGoalId"
                      :options="parentGoalOptions"
                      dense
                      outlined
                      hide-bottom-space
                      emit-value
                      map-options
                      use-input
                      input-debounce="0"
                      class="q-mt-sm"
                      :label="t('goal.triggerAfterGoal')"
                      :hint="t('goal.triggerAfterGoalHint')"
                      :rules="[requiredRule]"
                    >
                      <template #prepend>
                        <q-icon name="account_tree" color="secondary" />
                      </template>
                      <template #selected-item="scope">
                        <span class="ellipsis">{{ scope.opt.label }}</span>
                      </template>
                      <template #no-option>
                        <q-item>
                          <q-item-section class="text-grey-7">
                            {{ t('goal.noTriggerGoal') }}
                          </q-item-section>
                        </q-item>
                      </template>
                    </q-select>
                  </q-card-section>
                </q-card>
              </div>
              <q-card
                v-if="form.triggerMode === 'TEMPORAL_CUSTOM'"
                flat
                class="goal-schedule-section goal-edit-section--full"
              >
                <q-card-section class="q-pa-sm">
                  <div class="goal-role-legend row items-center q-gutter-xs text-primary q-mb-sm">
                    <q-icon name="calendar_month" size="18px" />
                    <span class="text-subtitle2">{{ t('goal.runtime.scheduleTitle') }}</span>
                  </div>
                  <GoalScheduleEditor
                    v-model:enabled="scheduleEnabledDraft"
                    v-model:slots="scheduleDraft"
                    :allowed-slots="globalAllowedSlots"
                    :show-enabled-toggle="false"
                  />
                </q-card-section>
              </q-card>
              <q-toggle
                v-if="!editingGoal"
                v-model="form.active"
                class="goal-edit-section--full"
                color="primary"
                :label="t('goal.startImmediately')"
              />
            </q-card-section>
            <q-separator />
            <q-card-actions align="right" class="q-pa-sm galaris-dialog-actions">
              <q-btn flat :label="t('common.cancel')" @click="cancelGoalEdit" />
              <q-btn
                color="primary"
                type="submit"
                :label="editingGoal ? t('common.save') : t('common.create')"
                :loading="formSaving"
                :disable="!form.description.trim() || !canSaveGoalTrigger"
              />
            </q-card-actions>
          </q-form>
        </q-tab-panel>
        </q-tab-panels>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useInterval, useQuasar, type QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import {
  RichText,
  RichTextEditor,
  PageHeader,
  WorkingDocumentEditor,
} from '@/core/util'
import { apiErrorDetail, isCancelledRequest } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useAuthStore } from '@/core/user'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import { AgentSelect } from '@/app/agent'
import GoalScheduleEditor from '../components/GoalScheduleEditor.vue'
import { goalService } from '../services/goalService'
import {
  goalScheduleDefaultSlots,
  goalScheduleSlotsToWindows,
  goalScheduleWindowsToSlots,
  type GoalScheduleSlots,
} from '../scheduleGrid'
import { useGoalStore } from '../stores/goalStore'
import type {
  Goal,
  GoalCycle,
  GoalReferrerInput,
  GoalStatus,
  GoalTreeNode,
  MessengerReferrerOption,
} from '../types'

type DurationUnit = 'seconds' | 'minutes' | 'hours' | 'days'
type GoalCommandName = 'pause' | 'resume' | 'complete' | 'runNow'
type GoalTriggerMode = 'TEMPORAL_DEFAULT' | 'TEMPORAL_CUSTOM' | 'RELATIONAL'
type GoalDialogTab = 'overview' | 'tracking' | 'cycles' | 'edit'

interface GoalFormState {
  title: string
  description: string
  agentId: number | null
  messengerReferrer: MessengerReferrerOption | null
  referrerMaxReminders: number
  triggerMode: GoalTriggerMode
  delayValue: number
  delayUnit: DurationUnit
  parentGoalId: string | null
  active: boolean
}

interface GoalHierarchyItem extends GoalTreeNode {
  depth: number
}

const UNIT_SECONDS: Record<DurationUnit, number> = {
  seconds: 1,
  minutes: 60,
  hours: 3600,
  days: 86400,
}

const { t, locale } = useI18n()
const $q = useQuasar()
const router = useRouter()
const route = useRoute()

const store = useGoalStore()
const agentStore = useAgentStore()
const privilegeStore = usePrivilegeStore()
const authStore = useAuthStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.GOAL_EDIT))
const canManageAllAgents = computed(() => (
  privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL)
))
const canViewLlm = computed(() => (
  privilegeStore.hasPrivilege(privileges.LLM_PROVIDER_ACCESS)
  || privilegeStore.hasPrivilege(privileges.LLM_PROVIDER_EDIT)
))
const canConfigureTrackingLlm = computed(() => (
  canViewLlm.value && privilegeStore.hasPrivilege(privileges.PARAMS_EDIT)
))
const canViewTasks = computed(() => (
  privilegeStore.hasPrivilege(privileges.TASK_ACCESS)
  || privilegeStore.hasPrivilege(privileges.TASK_EDIT)
))
const { registerInterval: registerSettingsRefresh } = useInterval()
let disposed = false

const goalDialogOpen = ref(false)
watch(goalDialogOpen, open => { if (!open) store.clearSelection() })
const goalDialogTab = ref<GoalDialogTab>('overview')
const goalDialogTitle = ref('')
const globalScheduleDialogOpen = ref(false)
const scheduleEnabledDraft = ref(false)
const scheduleDraft = ref<GoalScheduleSlots>(goalScheduleDefaultSlots())
const globalScheduleEnabledDraft = ref(false)
const globalScheduleDraft = ref<GoalScheduleSlots>(goalScheduleDefaultSlots())
const formSaving = ref(false)
const commandGoalIds = reactive(new Set<string>())
const editingGoal = ref<Goal | null>(null)
const messengerReferrerOptions = ref<MessengerReferrerOption[]>([])
const messengerSearching = ref(false)
let messengerSearchSequence = 0
const form = reactive<GoalFormState>({
  title: '',
  description: '',
  agentId: null,
  messengerReferrer: null,
  referrerMaxReminders: 1,
  triggerMode: 'TEMPORAL_DEFAULT',
  delayValue: 1,
  delayUnit: 'hours',
  parentGoalId: null,
  active: true,
})

function invalidateMessengerSearch(): void {
  messengerSearchSequence += 1
  messengerSearching.value = false
}
watch(() => form.agentId, invalidateMessengerSearch, { flush: 'sync' })
watch(goalDialogOpen, open => { if (!open) invalidateMessengerSearch() }, { flush: 'sync' })

const agentOptions = computed(() => agentStore.sortedAgents.map(agent => ({
  label: `${agentStore.getFullName(agent, t)} (@${agent.code})`,
  value: agent.id,
})))

const statusOptions = computed(() => (
  (['ACTIVE', 'PAUSED', 'COMPLETED', 'ERROR'] as GoalStatus[]).map(value => ({
    label: statusLabel(value),
    value,
  }))
))

const runtimeColor = computed(() => {
  if (store.settings?.inactive_reason === 'GLOBAL_PAUSE') return 'negative'
  if (store.settings?.inactive_reason === 'OUTSIDE_SCHEDULE') return 'warning'
  return 'positive'
})

const runtimeIcon = computed(() => {
  if (store.settings?.inactive_reason === 'GLOBAL_PAUSE') return 'pause_circle'
  if (store.settings?.inactive_reason === 'OUTSIDE_SCHEDULE') return 'event_busy'
  return 'play_circle'
})

const runtimeStatusLabel = computed(() => {
  if (store.settings?.inactive_reason === 'GLOBAL_PAUSE') {
    return t('goal.runtime.globalPaused')
  }
  if (store.settings?.inactive_reason === 'OUTSIDE_SCHEDULE') {
    return t('goal.runtime.outsideGlobalSchedule')
  }
  return t('goal.runtime.active')
})

const runtimeDescription = computed(() => {
  const settings = store.settings
  if (!settings) return ''
  if (settings.inactive_reason === 'GLOBAL_PAUSE') {
    return t('goal.runtime.globalPausedDescription')
  }
  if (settings.inactive_reason === 'OUTSIDE_SCHEDULE') {
    return t('goal.runtime.outsideGlobalScheduleDescription', {
      next: formatDate(settings.next_active_at),
    })
  }
  if (!settings.schedule_enabled) {
    return t('goal.runtime.globalScheduleDisabledDescription')
  }
  return t('goal.runtime.activeDescription')
})

const canSaveSchedule = computed(() => (
  form.triggerMode !== 'TEMPORAL_CUSTOM'
  || scheduleDraft.value.size > 0
))

const canSaveGoalTrigger = computed(() => (
  form.triggerMode === 'RELATIONAL'
    ? form.parentGoalId !== null
    : canSaveSchedule.value
))

const canSaveGlobalSchedule = computed(() => (
  !globalScheduleEnabledDraft.value
  || globalScheduleDraft.value.size > 0
))

const globalAllowedSlots = computed<GoalScheduleSlots | undefined>(() => {
  const settings = store.settings
  if (!settings?.schedule_enabled) return undefined
  return goalScheduleWindowsToSlots(settings.schedule)
})

const durationUnitOptions = computed(() => (
  (['seconds', 'minutes', 'hours', 'days'] as DurationUnit[]).map(value => ({
    label: t(`goal.units.${value}`),
    value,
  }))
))

const triggerModeOptions = computed(() => (
  ([
    ['TEMPORAL_DEFAULT', 'goal.temporalDefaultTrigger'],
    ['TEMPORAL_CUSTOM', 'goal.temporalCustomTrigger'],
    ['RELATIONAL', 'goal.relationalTrigger'],
  ] as const).map(([value, label]) => ({ value, label: t(label) }))
))

const treeGoalById = computed(() => new Map(
  store.treeGoals.map(goal => [goal.id, goal]),
))

function descendantIds(goalId: string): Set<string> {
  const result = new Set<string>()
  let frontier = [goalId]
  while (frontier.length) {
    const parents = new Set(frontier)
    frontier = store.treeGoals
      .filter(goal => goal.parent_goal_id && parents.has(goal.parent_goal_id) && !result.has(goal.id))
      .map(goal => goal.id)
    frontier.forEach(id => result.add(id))
  }
  return result
}

const parentGoalOptions = computed(() => {
  const editingId = editingGoal.value?.id ?? null
  const excluded = editingId ? descendantIds(editingId) : new Set<string>()
  if (editingId) excluded.add(editingId)
  return store.treeGoals
    .filter(goal => !excluded.has(goal.id))
    .map(goal => ({
      label: `${goal.title} · ${goal.agent_name} (@${goal.agent_code})`,
      value: goal.id,
    }))
})

function flattenGoalHierarchy(
  nodes: GoalTreeNode[],
  parentId: string | null = null,
  depth = 0,
  seen: Set<string> = new Set(),
): GoalHierarchyItem[] {
  const result: GoalHierarchyItem[] = []
  for (const node of nodes.filter(item => item.parent_goal_id === parentId)) {
    if (seen.has(node.id)) continue
    seen.add(node.id)
    result.push({ ...node, depth })
    result.push(...flattenGoalHierarchy(nodes, node.id, depth + 1, seen))
  }
  return result
}

const hierarchyItems = computed(() => flattenGoalHierarchy(store.treeGoals))

const hierarchicalGoals = computed(() => {
  const order = new Map(hierarchyItems.value.map((goal, index) => [goal.id, index]))
  return store.goals
    .map((goal, index) => ({ goal, index }))
    .sort((left, right) => (
      (order.get(left.goal.id) ?? Number.MAX_SAFE_INTEGER)
      - (order.get(right.goal.id) ?? Number.MAX_SAFE_INTEGER)
      || left.index - right.index
    ))
    .map(item => item.goal)
})

function goalDepth(goalId: string): number {
  let depth = 0
  let parentId = treeGoalById.value.get(goalId)?.parent_goal_id ?? null
  const seen = new Set<string>([goalId])
  while (parentId && !seen.has(parentId)) {
    seen.add(parentId)
    depth += 1
    parentId = treeGoalById.value.get(parentId)?.parent_goal_id ?? null
  }
  return depth
}

function goalIndentStyle(goalId: string): Record<string, string> {
  return { paddingInlineStart: `${goalDepth(goalId) * 24}px` }
}

function parentGoalTitle(goal: Pick<Goal, 'parent_goal_id' | 'parent_title'>): string | null {
  if (!goal.parent_goal_id) return null
  return goal.parent_title ?? treeGoalById.value.get(goal.parent_goal_id)?.title ?? null
}

const currentParentNode = computed(() => {
  const parentId = store.currentGoal?.parent_goal_id
  return parentId ? treeGoalById.value.get(parentId) ?? null : null
})

const currentSubGoalRows = computed(() => (
  store.currentGoal
    ? flattenGoalHierarchy(store.treeGoals, store.currentGoal.id, 1)
    : []
))

const columns = computed<QTableColumn<Goal>[]>(() => [
  { name: 'title', label: t('goal.title'), field: 'title', align: 'left' },
  { name: 'agent', label: t('goal.agent'), field: 'agent_name', align: 'left' },
  { name: 'trigger', label: t('goal.automaticTriggers'), field: 'parent_goal_id', align: 'left' },
  { name: 'status', label: t('goal.status'), field: 'status', align: 'left' },
  { name: 'cycles', label: t('goal.cycles'), field: 'cycle_count', align: 'right' },
  { name: 'next_cycle_at', label: t('goal.nextCycle'), field: 'next_cycle_at', align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
])

const metrics = computed(() => [
  { key: 'active', label: t('goal.metrics.active'), value: store.summary.active, icon: 'play_circle', color: 'positive' },
  { key: 'paused', label: t('goal.metrics.paused'), value: store.summary.paused, icon: 'pause_circle', color: 'warning' },
  { key: 'completed', label: t('goal.metrics.completed'), value: store.summary.completed, icon: 'check_circle', color: 'primary' },
  { key: 'errors', label: t('goal.metrics.errors'), value: store.summary.errors, icon: 'error', color: 'negative' },
  { key: 'cost', label: t('goal.totalCost'), value: formatCost(store.summary.total_cost), icon: 'payments', color: 'secondary' },
])

const displayPage = computed({
  get: () => store.page + 1,
  set: (value: number) => { void store.fetchGoals(value - 1) },
})

const displayCyclePage = computed({
  get: () => store.cyclePage,
  set: (value: number) => {
    if (store.currentGoal) void store.fetchCycles(store.currentGoal.id, value)
  },
})

const cyclePaginationMaxPages = computed(() => ($q.screen.lt.sm ? 3 : 7))

const cycleRangeStart = computed(() => (
  store.cycleTotal ? (store.cyclePage - 1) * store.cyclePageSize + 1 : 0
))

const cycleRangeEnd = computed(() => Math.min(
  store.cyclePage * store.cyclePageSize,
  store.cycleTotal,
))

function statusLabel(status: GoalStatus): string {
  return t(`goal.statuses.${status}`)
}

function statusColor(status: GoalStatus): string {
  return { ACTIVE: 'positive', PAUSED: 'warning', COMPLETED: 'primary', ERROR: 'negative' }[status]
}

function statusIcon(status: GoalStatus): string {
  return { ACTIVE: 'play_circle', PAUSED: 'pause_circle', COMPLETED: 'check_circle', ERROR: 'error' }[status]
}

function cycleStatusLabel(status: GoalCycle['status']): string {
  return t(`goal.cycleStatuses.${status}`)
}

function verdictLabel(verdict: NonNullable<GoalCycle['verdict']>): string {
  return t(`goal.verdicts.${verdict}`)
}

function cycleColor(cycle: GoalCycle): string {
  if (cycle.status === 'ERROR') return 'negative'
  if (cycle.verdict === 'STOP') return 'primary'
  if (cycle.verdict === 'CONTINUE') return 'positive'
  if (cycle.status === 'JUDGING') return 'secondary'
  return 'grey-7'
}

function formatCost(value: number): string {
  return new Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(value || 0)
}

function formatDate(value: string | null): string {
  if (!value) return t('goal.never')
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return t('goal.disabled')
  if (seconds === 0) return `0 ${t('goal.units.seconds')}`
  for (const unit of ['days', 'hours', 'minutes'] as DurationUnit[]) {
    const factor = UNIT_SECONDS[unit]
    if (seconds % factor === 0) return `${seconds / factor} ${t(`goal.units.${unit}`)}`
  }
  return `${seconds} ${t('goal.units.seconds')}`
}

function splitDuration(seconds: number | null): { value: number; unit: DurationUnit } {
  if (seconds === null) return { value: 1, unit: 'hours' }
  for (const unit of ['days', 'hours', 'minutes'] as DurationUnit[]) {
    const factor = UNIT_SECONDS[unit]
    if (seconds > 0 && seconds % factor === 0) return { value: seconds / factor, unit }
  }
  return { value: seconds, unit: 'seconds' }
}

function requiredRule(value: unknown): true | string {
  return (typeof value === 'number' || String(value || '').trim().length > 0) || t('common.required')
}

function nonNegativeRule(value: number | null): true | string {
  return (value !== null && Number.isFinite(Number(value)) && Number(value) >= 0) || t('common.required')
}

function nonNegativeIntegerRule(value: number | null): true | string {
  return (
    value !== null
    && Number.isInteger(Number(value))
    && Number(value) >= 0
  ) || t('common.required')
}

function resetForm(): void {
  messengerReferrerOptions.value = []
  scheduleEnabledDraft.value = false
  scheduleDraft.value = goalScheduleDefaultSlots()
  Object.assign(form, {
    title: '',
    description: '',
    agentId: agentOptions.value[0]?.value ?? null,
    messengerReferrer: null,
    referrerMaxReminders: 1,
    triggerMode: 'TEMPORAL_DEFAULT' as GoalTriggerMode,
    delayValue: 1,
    delayUnit: 'hours' as DurationUnit,
    parentGoalId: null,
    active: true,
  })
}

function scheduleDraftFromWindows(windows: Goal['schedule']): GoalScheduleSlots {
  return windows.length > 0
    ? goalScheduleWindowsToSlots(windows)
    : goalScheduleDefaultSlots()
}

function setGoalTriggerMode(value: unknown): void {
  if (
    value !== 'TEMPORAL_DEFAULT'
    && value !== 'TEMPORAL_CUSTOM'
    && value !== 'RELATIONAL'
  ) return
  form.triggerMode = value
  scheduleEnabledDraft.value = value === 'TEMPORAL_CUSTOM'
  if (scheduleEnabledDraft.value && scheduleDraft.value.size === 0) {
    scheduleDraft.value = goalScheduleDefaultSlots()
  }
}

function openCreateDialog(): void {
  editingGoal.value = null
  goalDialogTitle.value = ''
  resetForm()
  goalDialogTab.value = 'edit'
  goalDialogOpen.value = true
  void selectCurrentUserReferrer(false)
}

function prepareGoalForm(goal: Goal): void {
  editingGoal.value = goal
  goalDialogTitle.value = goal.title
  const delay = splitDuration(goal.cycle_delay_seconds)
  const messengerReferrer = goal.referrer?.type === 'MESSENGER'
    && goal.referrer.connection_id
    && goal.referrer.user_id
    ? {
        connection_id: goal.referrer.connection_id,
        tool_id: 0,
        platform: goal.referrer.platform || 'messenger',
        user_id: goal.referrer.user_id,
        display_name: goal.referrer.display_name,
        is_current_user: (
          goal.referrer.platform === 'internal'
          && goal.referrer.user_id === `user:${authStore.user?.id}`
        ),
      }
    : null
  messengerReferrerOptions.value = messengerReferrer ? [messengerReferrer] : []
  scheduleEnabledDraft.value = goal.schedule_enabled
  scheduleDraft.value = scheduleDraftFromWindows(goal.schedule)
  Object.assign(form, {
    title: goal.title,
    description: goal.description,
    agentId: goal.agent_id,
    messengerReferrer,
    referrerMaxReminders: goal.referrer_max_reminders,
    triggerMode: goal.parent_goal_id !== null
      ? 'RELATIONAL'
      : goal.schedule_enabled ? 'TEMPORAL_CUSTOM' : 'TEMPORAL_DEFAULT',
    delayValue: delay.value,
    delayUnit: delay.unit,
    parentGoalId: goal.parent_goal_id,
    active: goal.status === 'ACTIVE',
  })
}

function cancelGoalEdit(): void {
  if (!editingGoal.value) {
    goalDialogOpen.value = false
    return
  }
  if (store.currentGoal) prepareGoalForm(store.currentGoal)
  goalDialogTab.value = 'overview'
}

function openGlobalScheduleDialog(): void {
  const settings = store.settings
  if (!settings) return
  globalScheduleEnabledDraft.value = settings.schedule_enabled
  globalScheduleDraft.value = scheduleDraftFromWindows(settings.schedule)
  globalScheduleDialogOpen.value = true
}

async function submitGlobalScheduleDialog(): Promise<void> {
  if (!canSaveGlobalSchedule.value) return
  try {
    await store.updateSettings({
      schedule_enabled: globalScheduleEnabledDraft.value,
      schedule: goalScheduleSlotsToWindows(globalScheduleDraft.value),
    })
    globalScheduleDialogOpen.value = false
    $q.notify({ type: 'positive', message: t('goal.runtime.globalScheduleUpdated') })
  } catch (error) {
    notifyError(error)
  }
}

async function submitForm(): Promise<void> {
  if (
    form.agentId === null
    || !form.description.trim()
    || !canSaveGoalTrigger.value
  ) return
  if (form.messengerReferrer === null) return
  const referrer: GoalReferrerInput = {
    type: 'MESSENGER',
    connection_id: form.messengerReferrer.connection_id,
    user_id: form.messengerReferrer.user_id,
    display_name: form.messengerReferrer.display_name,
  }
  formSaving.value = true
  try {
    const temporalTrigger = form.triggerMode !== 'RELATIONAL'
    const cycleDelay = temporalTrigger
      ? Math.round(Number(form.delayValue) * UNIT_SECONDS[form.delayUnit])
      : null
    const parentGoalId = temporalTrigger ? null : form.parentGoalId
    const scheduleEnabled = form.triggerMode === 'TEMPORAL_CUSTOM'
    const schedule = scheduleEnabled
      ? goalScheduleSlotsToWindows(scheduleDraft.value)
      : []
    if (editingGoal.value) {
      const updated = await store.updateGoal(editingGoal.value.id, {
        expected_revision: editingGoal.value.revision,
        title: form.title.trim(),
        description: form.description.trim(),
        agent_id: form.agentId,
        referrer,
        cycle_delay_seconds: cycleDelay,
        parent_goal_id: parentGoalId,
        schedule_enabled: scheduleEnabled,
        schedule,
        referrer_max_reminders: Math.max(0, Math.trunc(form.referrerMaxReminders)),
      })
      await store.fetchGoal(updated.id)
      if (store.currentGoal) prepareGoalForm(store.currentGoal)
      $q.notify({ type: 'positive', message: t('goal.updated') })
    } else {
      const created = await store.createGoal({
        title: form.title.trim(),
        description: form.description.trim(),
        agent_id: form.agentId,
        referrer,
        cycle_delay_seconds: cycleDelay,
        parent_goal_id: parentGoalId,
        schedule_enabled: scheduleEnabled,
        schedule,
        referrer_max_reminders: Math.max(0, Math.trunc(form.referrerMaxReminders)),
        active: form.active,
      })
      await store.fetchGoal(created.id, 1)
      if (store.currentGoal) prepareGoalForm(store.currentGoal)
      $q.notify({ type: 'positive', message: t('goal.created') })
    }
    goalDialogTab.value = 'overview'
  } catch (error) {
    notifyError(error)
  } finally {
    formSaving.value = false
  }
}

async function openDetails(goal: Goal): Promise<void> {
  prepareGoalForm(goal)
  goalDialogTab.value = 'overview'
  goalDialogOpen.value = true
  try {
    const currentGoal = await store.fetchGoal(goal.id, 1)
    if (currentGoal && goalDialogOpen.value) prepareGoalForm(currentGoal)
  } catch (error) {
    notifyError(error)
  }
}

async function openEdit(goal: Goal): Promise<void> {
  prepareGoalForm(goal)
  goalDialogTab.value = 'edit'
  goalDialogOpen.value = true
  try {
    const currentGoal = await store.fetchGoal(goal.id, 1)
    if (currentGoal && goalDialogOpen.value) prepareGoalForm(currentGoal)
  } catch (error) {
    notifyError(error)
  }
}

async function openGoalDetailsById(goalId: string): Promise<void> {
  const listedGoal = store.goals.find(goal => goal.id === goalId)
  if (listedGoal) {
    prepareGoalForm(listedGoal)
  } else {
    editingGoal.value = null
    goalDialogTitle.value = treeGoalById.value.get(goalId)?.title ?? ''
  }
  goalDialogTab.value = 'overview'
  goalDialogOpen.value = true
  try {
    const currentGoal = await store.fetchGoal(goalId, 1)
    if (currentGoal && goalDialogOpen.value) prepareGoalForm(currentGoal)
  } catch (error) {
    notifyError(error)
  }
}

async function runCommand(action: GoalCommandName, goal: Goal): Promise<void> {
  if (commandGoalIds.has(goal.id)) return
  commandGoalIds.add(goal.id)
  try {
    await store.command(action, goal)
    if (store.currentGoal?.id === goal.id) await store.fetchGoal(goal.id)
    $q.notify({
      type: 'positive',
      message: t(action === 'runNow' ? 'goal.runNowQueued' : 'goal.commandDone'),
    })
  } catch (error) {
    notifyError(error)
  } finally {
    commandGoalIds.delete(goal.id)
  }
}

async function toggleGlobalPause(): Promise<void> {
  if (!store.settings) return
  try {
    const globallyPaused = !store.settings.globally_paused
    await store.updateSettings({ globally_paused: globallyPaused })
    $q.notify({
      type: 'positive',
      message: t(globallyPaused
        ? 'goal.runtime.globalPauseEnabled'
        : 'goal.runtime.globalPauseDisabled'),
    })
  } catch (error) {
    notifyError(error)
  }
}

function confirmComplete(goal: Goal): void {
  showConfirmationDialog({
    title: t('goal.complete'),
    message: t('goal.completeConfirm', { title: goal.title }),
    cancel: true,
  }).onOk(() => { void runCommand('complete', goal) })
}

function confirmDelete(goal: Goal): void {
  showConfirmationDialog({
    title: t('goal.delete'),
    message: t('goal.deleteConfirm', { title: goal.title }),
    cancel: true,
  }).onOk(async () => {
    try {
      await store.deleteGoal(goal.id)
      goalDialogOpen.value = false
      $q.notify({ type: 'positive', message: t('goal.deleted') })
    } catch (error) {
      notifyError(error)
    }
  })
}

function notifyError(error: unknown): void {
  $q.notify({ type: 'negative', message: apiErrorDetail(error) || t('goal.error') })
}

function setOwnerAgent(value: number | null): void {
  if (form.agentId === value) return
  form.agentId = value
  form.messengerReferrer = null
  messengerReferrerOptions.value = []
  void selectCurrentUserReferrer(false)
}

async function selectCurrentUserReferrer(notifyWhenMissing = true): Promise<void> {
  const agentId = form.agentId
  const sequence = ++messengerSearchSequence
  if (agentId === null) return
  messengerSearching.value = true
  try {
    const options = await goalService.searchMessengerReferrers(agentId, '')
    if (sequence !== messengerSearchSequence) return
    messengerReferrerOptions.value = options
    const currentUser = options.find(option => option.is_current_user)
    if (currentUser) {
      form.messengerReferrer = currentUser
    } else if (notifyWhenMissing) {
      $q.notify({ type: 'warning', message: t('goal.referrerMeUnavailable') })
    }
  } catch (error) {
    if (sequence === messengerSearchSequence && !isCancelledRequest(error)) notifyError(error)
  } finally {
    if (sequence === messengerSearchSequence) messengerSearching.value = false
  }
}

function messengerOptionLabel(option: MessengerReferrerOption | string): string {
  if (typeof option === 'string') return option
  return t('goal.referrerContactOption', {
    name: option.display_name,
    messaging: messengerPlatformLabel(option.platform),
  })
}

const messengerPlatformKeys = new Set([
  'internal',
  'mail',
  'matrix',
  'nextcloud_talk',
  'one_bot',
  'telegram',
  'whatsapp',
])

function messengerPlatformLabel(platform: string): string {
  const normalized = platform.trim().toLowerCase()
  return messengerPlatformKeys.has(normalized)
    ? t(`goal.messengerPlatforms.${normalized}`)
    : platform
}

async function filterMessengerReferrers(
  value: string,
  update: (callback: () => void) => void,
  abort: () => void,
): Promise<void> {
  const query = value.trim()
  const agentId = form.agentId
  const sequence = ++messengerSearchSequence
  if (agentId === null) {
    update(() => {
      messengerReferrerOptions.value = form.messengerReferrer
        ? [form.messengerReferrer]
        : []
    })
    return
  }
  messengerSearching.value = true
  try {
    const options = await goalService.searchMessengerReferrers(agentId, query)
    if (sequence !== messengerSearchSequence) return
    update(() => {
      messengerReferrerOptions.value = options
    })
  } catch (error) {
    if (sequence !== messengerSearchSequence) return
    if (!isCancelledRequest(error)) notifyError(error)
    abort()
  } finally {
    if (sequence === messengerSearchSequence) messengerSearching.value = false
  }
}

function setSearch(value: string | number | null): void {
  store.search = String(value || '')
  void store.fetchGoals(0)
}

function setAgentFilter(value: number | null): void {
  store.agentFilter = value
  void store.fetchGoals(0)
}

function setStatusFilter(value: GoalStatus | null): void {
  store.statusFilter = value
  void store.fetchGoals(0)
}

function setPageSize(value: number | null): void {
  if (!value) return
  store.pageSize = value
  void store.fetchGoals(0)
}

function setCyclePageSize(value: number | null): void {
  if (!value || !store.currentGoal) return
  store.cyclePageSize = value
  void store.fetchCycles(store.currentGoal.id, 1)
}

function openTask(taskId: string): void {
  void router.push({ path: '/task', query: { task_id: taskId } })
}

onMounted(async () => {
  store.subscribe()
  try {
    await Promise.all([
      store.fetchGoals(0),
      store.fetchTree(),
      store.fetchSettings(),
      agentStore.fetchAgents(),
      agentStore.fetchTitles(),
    ])
    if (disposed) return
    registerSettingsRefresh(() => {
      void store.fetchSettings().catch(() => undefined)
    }, 60_000)
  } catch (error) {
    notifyError(error)
  }
})

onUnmounted(() => {
  disposed = true
  invalidateMessengerSearch()
  store.unsubscribe()
})
watch(() => route.query.goal_id, value => { if (typeof value === 'string' && /^[0-9a-f-]{36}$/.test(value)) void openGoalDetailsById(value) }, { immediate: true })
</script>

<style scoped>
.goal-schedule-dialog-card,
.goal-detail-dialog {
  border-radius: 12px;
}

.goal-schedule-dialog-card {
  display: flex;
  flex-direction: column;
  width: min(1100px, 96vw);
  max-width: 96vw;
  max-height: 92vh;
}

.goal-form {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}

.goal-form-content {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.goal-runtime-card {
  border-left-width: 4px;
  border-left-style: solid;
}

.goal-runtime-card--positive {
  border-left-color: var(--q-positive);
}

.goal-runtime-card--warning {
  border-left-color: var(--q-warning);
}

.goal-runtime-card--negative {
  border-left-color: var(--q-negative);
}

.goal-detail-content {
  box-sizing: border-box;
  width: 100%;
  padding: 16px;
  overflow-y: auto;
}

.goal-detail-dialog {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: min(1400px, calc(100vw - 32px));
  max-width: calc(100vw - 32px);
  height: min(900px, calc(100vh - 32px));
  max-height: calc(100vh - 32px);
  min-height: 0;
  overflow: hidden;
}

.goal-dialog-tabs {
  flex: 0 0 auto;
}

.goal-dialog-panels {
  flex: 1 1 auto;
  min-height: 0;
}

.goal-dialog-panels :deep(.q-panel),
.goal-dialog-panels :deep(.q-tab-panel) {
  height: 100%;
}

.goal-edit-tab .goal-form {
  width: 100%;
  height: 100%;
}

.goal-tracking-document-editor {
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  padding: 8px;
  overflow-y: auto;
}

.goal-edit-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.goal-edit-grid > * {
  min-width: 0;
}

.goal-edit-sidebar {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.goal-role-legend {
  margin-bottom: 8px;
}

.goal-role-legend--spaced {
  margin-top: 16px;
}

.goal-referrer-reminders {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  margin-top: 12px;
}

.goal-referrer-reminders-control {
  width: 100px;
}

.goal-referrer-reminders-hint {
  line-height: 1.35;
  white-space: pre-line;
}

.goal-trigger-options :deep(.q-radio) {
  align-items: flex-start;
}

.goal-trigger-options :deep(.q-radio__label) {
  padding-top: 1px;
}

.goal-edit-section--full {
  grid-column: 1 / -1;
}

.goal-detail-title {
  min-width: 0;
  column-gap: 8px;
  row-gap: 4px;
}

.goal-detail-title .text-h6 {
  min-width: 0;
  overflow-wrap: anywhere;
}

.goal-description-heading,
.goal-cycle-heading,
.goal-cycle-pagination,
.goal-cycle-page-size {
  min-width: 0;
}

.goal-description {
  line-height: 1.45;
}

.goal-llm-banner {
  border: 1px solid color-mix(in srgb, var(--q-negative) 35%, transparent);
  padding: 20px;
}

.goal-description-cell {
  max-width: 100%;
}

.goal-error-cell {
  max-width: 230px;
}

.goal-table :deep(.q-table__grid-content) {
  width: 100%;
  margin: 0;
}

.goal-table :deep(table) {
  width: 100%;
  table-layout: fixed;
}

.goal-table :deep(th),
.goal-table :deep(td) {
  padding: 6px 8px;
  vertical-align: middle;
}

.goal-table :deep(tbody tr) {
  cursor: pointer;
}

.goal-table :deep(th:nth-child(1)),
.goal-table :deep(td:nth-child(1)) {
  width: 24%;
}

.goal-table :deep(th:nth-child(2)),
.goal-table :deep(td:nth-child(2)) {
  width: 9%;
}

.goal-table :deep(th:nth-child(3)),
.goal-table :deep(td:nth-child(3)) {
  width: 17%;
}

.goal-table :deep(th:nth-child(4)),
.goal-table :deep(td:nth-child(4)) {
  width: 10%;
}

.goal-table :deep(th:nth-child(5)),
.goal-table :deep(td:nth-child(5)) {
  width: 6%;
}

.goal-table :deep(th:nth-child(6)),
.goal-table :deep(td:nth-child(6)) {
  width: 12%;
}

.goal-table :deep(th:nth-child(7)),
.goal-table :deep(td:nth-child(7)) {
  width: 22%;
}

.goal-trigger-cell,
.goal-trigger-cell > div,
.goal-table :deep(td) {
  overflow: hidden;
}

.goal-table :deep(.goal-list-actions-cell) {
  overflow: visible;
}

.goal-list-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: nowrap;
  gap: 0;
}

.goal-list-actions > * {
  flex: 0 0 auto;
}

.goal-mobile-card .goal-list-actions {
  flex-wrap: wrap;
}

.goal-grid-item {
  min-width: 0;
  max-width: 100%;
  padding: 8px 12px;
}

.goal-mobile-card,
.goal-mobile-heading {
  min-width: 0;
}

.goal-mobile-card {
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.goal-mobile-card:hover,
.goal-mobile-card:focus-visible {
  border-color: var(--q-primary);
  box-shadow: 0 3px 12px rgb(25 118 210 / 14%);
  outline: none;
}

.goal-mobile-title,
.goal-mobile-description {
  overflow-wrap: anywhere;
}

.goal-mobile-description {
  display: -webkit-box;
  overflow: hidden;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.goal-mobile-metadata {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
}

.goal-mobile-metadata > div {
  min-width: 0;
}

.goal-metadata-label {
  color: #667085;
  font-size: 0.75rem;
  line-height: 1.25;
}

.goal-page-heading {
  gap: 16px;
}

.goal-runtime-actions {
  gap: 8px;
}

:global(.body--dark) .goal-metadata-label {
  color: #98a2b8;
}

.goal-pagination {
  gap: 12px;
}

.goal-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
  gap: 16px;
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
  background: rgb(25 118 210 / 6%);
  overflow-wrap: anywhere;
}

:global(.body--dark) .goal-activity-metric {
  background: rgb(255 255 255 / 7%);
}

.goal-activity-metric--wide {
  grid-column: 1 / -1;
}

.goal-cost-breakdown {
  margin-top: 10px;
  overflow-wrap: anywhere;
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

@media (min-width: 1200px) {
  .goal-edit-grid {
    grid-template-columns: minmax(0, 13fr) minmax(0, 7fr);
  }
}

@media (min-width: 1024px) {
  .goal-cycles-timeline :deep(.q-timeline__subtitle) {
    width: clamp(170px, 18vw, 220px);
    padding-right: 16px;
  }

  .goal-cycles-timeline :deep(.q-timeline__content) {
    padding-left: 16px;
  }
}

@media (max-width: 1023px) {
  .goal-runtime-actions {
    padding-left: 0;
  }

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

  .goal-cycles-timeline {
    display: block;
  }

  .goal-cycles-timeline :deep(.q-timeline__entry) {
    display: block;
    padding-left: 32px;
  }

  .goal-cycles-timeline :deep(.q-timeline__subtitle) {
    display: none;
  }

  .goal-cycles-timeline :deep(.q-timeline__dot) {
    position: absolute;
    min-width: 0;
  }

  .goal-cycles-timeline :deep(.q-timeline__content) {
    display: block;
    width: 100%;
    padding-top: 0;
    padding-left: 0;
  }

  .goal-cycle-mobile-date {
    display: block;
    margin-top: -8px;
    margin-bottom: 8px;
  }
}

@media (max-width: 599.98px) {
  .goal-page {
    padding: 8px;
  }

  .goal-page-heading {
    display: grid;
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .goal-page-heading .q-btn,
  .goal-runtime-actions .q-btn {
    width: 100%;
    margin: 0;
  }

  .goal-summary-metric-card :deep(.q-card__section) {
    padding: 12px;
  }

  .goal-summary-metric-card :deep(.q-avatar) {
    font-size: 36px;
  }

  .goal-summary-metric-card :deep(.q-ml-md) {
    margin-left: 8px;
  }

  .goal-runtime-actions {
    display: grid;
    grid-template-columns: 1fr;
    gap: 8px;
  }

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

  .goal-description-heading,
  .goal-cycle-heading,
  .goal-cycle-pagination,
  .goal-cycle-page-size {
    align-items: stretch;
    flex-direction: column;
  }

  .goal-description-heading,
  .goal-cycle-heading,
  .goal-cycle-pagination {
    gap: 8px;
  }

  .goal-description-heading .q-btn,
  .goal-cycle-heading .q-btn {
    width: 100%;
  }

  .goal-description-heading .q-space,
  .goal-cycle-heading .q-space {
    display: none;
  }

  .goal-description-heading > *,
  .goal-cycle-heading > * {
    margin: 0;
  }

  .goal-cycle-page-size {
    gap: 4px;
  }

  .goal-cycle-pagination :deep(.q-pagination) {
    align-self: center;
    max-width: 100%;
  }

  .goal-grid-item {
    padding: 8px;
  }

  .goal-pagination {
    flex-wrap: wrap;
  }

  .goal-detail-content {
    padding: 8px;
  }

  .goal-overview-section {
    padding: 12px;
  }

}
</style>
