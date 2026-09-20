<template>
    <q-card v-if="task" class="task-detail" flat bordered>
        <!-- Header -->
        <q-card-section :class="getHeaderBgClass(task.status)">
            <div class="row items-center">
                <!-- Suspension takes visual precedence over the stored resume phase. -->
                <q-spinner
                    v-if="working"
                    :color="getTaskOperationalColor(task)"
                    size="md"
                    class="q-mr-sm"
                />
                <q-icon
                    v-else
                    :name="getTaskOperationalIcon(task)"
                    :color="getTaskOperationalColor(task)"
                    size="md"
                    class="q-mr-sm"
                />
                <div class="col">
                    <!-- First row: title and badges. -->
                    <div class="row items-center justify-between task-header-row">
                        <div class="row items-center q-gutter-x-sm">
                            <span>{{ task.label }}</span>
                            <div v-if="task.agent_id != null" class="task-header-agent">
                                <q-avatar size="24px" color="white" text-color="grey-7">
                                    <img v-if="assignedAgentAvatarUrl" :src="assignedAgentAvatarUrl" alt="" />
                                    <q-icon v-else name="person" size="16px" />
                                </q-avatar>
                                <span class="task-header-agent-name">{{ assignedAgentName }}</span>
                                <q-tooltip>{{ $t('task.detail.assignedAgent') }}</q-tooltip>
                            </div>
                        </div>
                        <div class="row items-center q-gutter-x-xs">
                            <q-badge v-if="task.ai" color="purple">AI</q-badge>
                            <StatusBadge
                                v-if="pauseState"
                                :tone="pauseState.tone"
                                :label="$t(pauseState.labelKey)"
                                :icon="pauseState.icon"
                            />
                            <q-badge v-if="subtaskEffort" :color="getEffortColor(subtaskEffort)" text-color="white">
                                {{ $t(`task.dispatch.effortLevels.${subtaskEffort}`) }}
                            </q-badge>
                            <StatusBadge
                                :tone="getTaskStatusTone(task.status)"
                                :label="t(`task.status.${task.status}`)"
                            />
                        </div>
                    </div>
                    <!-- Second row: task UUID, timestamps, and actions. -->
                    <div class="row items-center justify-between q-mt-xs task-header-row">
                        <div class="row items-center q-gutter-x-sm">
                            <div class="text-caption text-grey cursor-pointer task-id" @click="copyTaskIdToClipboard" :title="$t('task.detail.copyIdTitle')">
                                {{ task.id }}
                            </div>
                            <q-separator vertical size="1px" color="grey-5" />
                            <div class="row items-center text-caption text-grey">
                                <q-icon name="event" size="xs" class="q-mr-xs" />
                                {{ formatDate(task.created_at) }}
                            </div>
                            <q-separator vertical size="1px" color="grey-5" />
                            <div class="row items-center text-caption text-grey">
                                <q-icon name="update" size="xs" class="q-mr-xs" />
                                {{ formatDate(task.updated_at) }}
                            </div>
                        </div>
                        <div class="row justify-end q-gutter-sm">
                            <TaskLabCaptureMenu
                                v-if="canEditLab"
                                :task-id="task.id"
                                :task-label="task.label"
                                :has-dispatcher="Boolean(task.dispatch_result)"
                                :has-briefing="Boolean(task.briefing_result)"
                                :has-planner="Boolean(task.plan)"
                                :has-executor="Boolean(task.execution_result)"
                            />
                            <q-btn size="sm" color="secondary" icon="content_copy" :label="$t('task.detail.jsonExport')" @click="copyJsonToClipboard">
                                <q-tooltip>{{ $t('task.detail.copyJsonTooltip') }}</q-tooltip>
                            </q-btn>
                            <q-btn v-if="canEdit && canRun" size="sm" color="green" icon="play_arrow" :label="$t('task.detail.run')"
                                @click="onRun" :loading="running">
                                <q-tooltip>{{ $t('task.detail.runTooltip') }}</q-tooltip>
                            </q-btn>
                            <q-btn v-if="canEdit && canPause" size="sm" color="orange" icon="pause" :label="$t('task.detail.pause')"
                                @click="onPause" :loading="pausing">
                                <q-tooltip>{{ $t('task.detail.pauseTooltip') }}</q-tooltip>
                            </q-btn>
                            <q-btn v-if="canEdit && canResume" size="sm" color="positive" icon="play_arrow" :label="$t('task.detail.resume')"
                                @click="onResume" :loading="pausing">
                                <q-tooltip>{{ $t('task.detail.resumeTooltip') }}</q-tooltip>
                            </q-btn>
                            <q-btn v-if="canEdit && canForceTerminate" size="sm" color="negative" outline icon="cancel"
                                :label="$t('task.detail.forceTerminate')" @click="confirmForceTerminate" :loading="forceTerminating">
                                <q-tooltip>{{ $t('task.detail.forceTerminateTooltip') }}</q-tooltip>
                            </q-btn>
                            <q-btn v-if="canEdit && canRetry" size="sm" color="primary" icon="replay"
                                :label="$t(isDeliveryRecoveryReady ? 'task.detail.retryDelivery' : 'task.detail.retry')"
                                @click="onRetry" :loading="retrying">
                                <q-tooltip>{{ $t(isDeliveryRecoveryReady ? 'task.detail.retryDeliveryTooltip' : 'task.detail.retryTooltip') }}</q-tooltip>
                            </q-btn>
                            <q-btn v-if="canEdit" size="sm" color="negative" icon="delete" :label="$t('common.delete')" @click="onDelete"
                                :disable="isSystemTask">
                                <q-tooltip v-if="isSystemTask">{{ $t('task.detail.systemCantDelete') }}</q-tooltip>
                                <q-tooltip v-else>{{ $t('task.detail.deleteTooltip') }}</q-tooltip>
                            </q-btn>
                        </div>
                    </div>
                </div>
            </div>
        </q-card-section>

        <q-card-section class="task-overview q-pb-none">
            <TopicAssignmentEditor
                :key="task.id"
                class="task-overview-topic"
                :topic-id="task.topic_id ?? null"
                :editable="canEdit"
                :saving="topicSaving"
                @save="saveTopic"
            />
        </q-card-section>

        <q-card-section>
            <!-- Parent task link for subtasks. -->
            <q-banner
                v-if="parentTask"
                dense
                rounded
                class="bg-blue-1 text-primary q-mb-md cursor-pointer"
                @click="onTaskClick(parentTask.id)"
            >
                <template v-slot:avatar>
                    <q-icon name="arrow_upward" color="primary" />
                </template>
                {{ $t('task.detail.parentTask') }} : <strong>{{ parentTask.label }}</strong>
                <template v-slot:action>
                    <q-btn flat icon="open_in_new" :label="$t('task.detail.openParent')" @click.stop="onTaskClick(parentTask.id)" />
                </template>
            </q-banner>

            <q-card v-if="activeReplyWaits.length" flat bordered class="q-mb-md bg-blue-1">
                <q-card-section>
                    <div class="row items-start q-col-gutter-md">
                        <div class="col-auto">
                            <q-icon name="forum" color="primary" size="28px" />
                        </div>
                        <div class="col">
                            <div class="text-subtitle2 text-primary q-mb-xs">
                                {{ $t('task.detail.parentWaitTitle') }}
                            </div>
                            <div class="text-body2 q-mb-sm">
                                {{ $t('task.detail.parentWaitDescription') }}
                            </div>
                            <q-list dense bordered separator class="rounded-borders bg-white">
                                <q-item v-for="wait in activeReplyWaits" :key="wait.id">
                                    <q-item-section>
                                        <q-item-label>{{ wait.question || $t('task.detail.parentWaitNoQuestion') }}</q-item-label>
                                        <q-item-label caption>
                                            {{ $t('task.detail.parentWaitPeer', { peer: wait.peer }) }}
                                            <template v-if="wait.deadline">
                                                · {{ $t('task.detail.parentWaitDeadline', { deadline: formatDate(wait.deadline) }) }}
                                            </template>
                                        </q-item-label>
                                    </q-item-section>
                                    <q-item-section side>
                                        <StatusBadge
                                            tone="warning"
                                            :label="$t('task.detail.coordinationAwaitPending')"
                                        />
                                    </q-item-section>
                                </q-item>
                            </q-list>
                        </div>
                    </div>
                </q-card-section>
            </q-card>

            <q-banner
                v-if="isDeliveryRecoveryReady"
                rounded
                class="bg-amber-1 text-amber-10 q-mb-md"
            >
                <template v-slot:avatar>
                    <q-icon name="outbox" color="amber-10" />
                </template>
                {{ $t('task.detail.deliveryPending', { filename: deliveryRecovery?.filename || '' }) }}
                <template v-slot:action>
                    <q-btn
                        v-if="canEdit"
                        flat
                        color="primary"
                        icon="replay"
                        :label="$t('task.detail.retryDelivery')"
                        :loading="retrying"
                        @click="onRetry"
                    />
                </template>
            </q-banner>

            <q-card v-if="isAwaitCoordinationTask" flat bordered class="q-mb-md bg-blue-1">
                <q-card-section>
                    <div class="row items-start q-col-gutter-md">
                        <div class="col-auto">
                            <q-icon name="hourglass_top" color="primary" size="28px" />
                        </div>
                        <div class="col">
                            <div class="text-subtitle2 text-primary q-mb-xs">
                                {{ $t('task.detail.coordinationAwaitTitle') }}
                            </div>
                            <div class="text-body2 q-mb-sm">
                                {{ $t('task.detail.coordinationAwaitDescription', { peer: awaitPeerLabel }) }}
                            </div>
                            <div class="row items-center q-gutter-sm">
                                <StatusBadge
                                    v-if="resolvedByTask"
                                    tone="success"
                                    :label="$t('task.detail.coordinationAwaitResolved')"
                                />
                                <StatusBadge
                                    v-else
                                    tone="warning"
                                    :label="$t('task.detail.coordinationAwaitPending')"
                                />
                                <q-btn
                                    v-if="resolvedByTask"
                                    flat
                                    color="primary"
                                    icon="open_in_new"
                                    :label="$t('task.detail.openResolvedTask')"
                                    @click="onTaskClick(resolvedByTask.id)"
                                />
                            </div>
                            <div v-if="resolvedByTask" class="text-caption text-grey-8 q-mt-xs">
                                {{ resolvedByTask.label }} · {{ resolvedByTask.id }}
                            </div>
                        </div>
                    </div>
                </q-card-section>
            </q-card>

            <!-- Task requester; the assigned agent is displayed in the header. -->
            <div v-if="requesterVisible" class="q-mb-md">
                <q-card flat bordered>
                    <q-card-section class="q-py-sm">
                        <div class="task-metadata">
                            <div class="task-metadata-item">
                                <q-avatar size="32px" color="grey-3" text-color="grey-7" class="task-metadata-avatar">
                                    <img v-if="requesterAgentAvatarUrl" :src="requesterAgentAvatarUrl" alt="" />
                                    <q-icon v-else name="person_add" size="20px" />
                                </q-avatar>
                                <div>
                                    <div class="task-metadata-label">{{ $t('task.detail.requesterAgent') }}</div>
                                    <div class="text-weight-bold">{{ requesterName }}</div>
                                </div>
                            </div>
                        </div>
                    </q-card-section>
                </q-card>
            </div>

            <!-- Canonical task objective. -->
            <div class="row q-col-gutter-md q-mb-md">
                <div class="col-12" :class="{ 'col-md-6': feedbackContent }">
                    <q-card v-if="task.objective" flat bordered class="full-height">
                        <q-card-section class="q-pa-sm">
                            <div class="text-subtitle2 q-mb-sm text-positive">
                                <q-icon name="flag" size="xs" class="q-mr-xs" />
                                {{ $t('task.form.objective') }}
                            </div>
                            <EditorialContent class="text-body2" :content="task.objective" :media-type="task.objective_media_type ?? 'text/markdown'" />
                        </q-card-section>
                    </q-card>
                    <q-banner v-else class="bg-grey-2 text-grey-7 full-height">
                        <template v-slot:avatar>
                            <q-icon name="flag" />
                        </template>
                        {{ $t('task.detail.noObjective') }}
                    </q-banner>
                </div>
                <div v-if="feedbackContent" class="col-12 col-md-6">
                    <q-card flat bordered class="full-height">
                        <q-card-section class="q-pa-sm">
                            <div class="text-subtitle2 q-mb-sm text-deep-orange">
                                <q-icon name="smart_toy" size="xs" class="q-mr-xs" />
                                {{ $t('task.detail.feedback') }}
                            </div>
                            <Markdown class="text-body2" :content="feedbackContent" />
                        </q-card-section>
                    </q-card>
                </div>
            </div>

            <!-- Frozen, auditable context selected before dispatch. -->
            <q-card v-if="contextCapsule" flat bordered class="q-mb-md">
                <q-expansion-item
                    icon="manage_search"
                    :label="$t('task.detail.contextCapsuleTitle')"
                    :caption="$t('task.detail.contextCapsuleCaption', { count: contextCapsule.entries.length })"
                    header-class="text-indigo"
                >
                    <q-separator />
                    <q-card-section class="q-pt-sm">
                        <div class="row items-center q-gutter-sm q-mb-sm">
                            <q-badge color="indigo" outline>
                                {{ $t('task.detail.contextCapsuleContact') }}: {{ contextCapsule.contact_memory_item_id }}
                            </q-badge>
                            <StatusBadge
                                v-if="contextCapsule.truncated"
                                tone="warning"
                                :label="$t('task.detail.contextCapsuleTruncated')"
                            />
                            <span class="text-caption text-grey-7">
                                {{ $t('task.detail.contextCapsuleFrozenAt', { date: formatDate(contextCapsule.created_at) }) }}
                            </span>
                        </div>
                        <q-list v-if="contextCapsule.entries.length" bordered separator class="rounded-borders">
                            <q-item v-for="entry in contextCapsule.entries" :key="entry.key">
                                <q-item-section avatar top>
                                    <q-icon :name="contextKindIcon(entry.kind)" color="indigo" />
                                </q-item-section>
                                <q-item-section>
                                    <q-item-label class="row items-center q-gutter-x-sm">
                                        <span>{{ entry.title || entry.reference }}</span>
                                        <q-badge color="grey-3" text-color="grey-9">
                                            {{ $t(`task.detail.contextKinds.${entry.kind}`) }}
                                        </q-badge>
                                    </q-item-label>
                                    <q-item-label v-if="entry.excerpt" caption class="context-capsule-excerpt q-mt-xs">
                                        {{ entry.excerpt }}
                                    </q-item-label>
                                    <q-item-label caption class="context-capsule-reference q-mt-xs">
                                        {{ entry.reference }}
                                        <template v-if="entry.revision"> · r{{ entry.revision }}</template>
                                        <template v-if="entry.occurred_at"> · {{ formatDate(entry.occurred_at) }}</template>
                                    </q-item-label>
                                    <q-item-label v-if="entry.provenance?.length" caption>
                                        {{ $t('task.detail.contextCapsuleSources') }}: {{ entry.provenance.join(' · ') }}
                                    </q-item-label>
                                </q-item-section>
                            </q-item>
                        </q-list>
                        <q-banner v-else dense class="bg-grey-2 text-grey-7 rounded-borders">
                            {{ $t('task.detail.contextCapsuleEmpty') }}
                        </q-banner>
                    </q-card-section>
                </q-expansion-item>
            </q-card>

            <!-- Plan steps linked to their clickable persisted child tasks. -->
            <q-card v-if="planRows.length" flat bordered class="q-mb-md">
                <q-card-section>
                    <div class="text-subtitle2 q-mb-sm text-primary">
                        <q-icon name="account_tree" size="xs" class="q-mr-xs" />
                        {{ $t('task.detail.subtasks') }}
                        <span class="text-caption text-grey q-ml-xs">{{ planDoneCount }}/{{ planRows.length }}</span>
                    </div>
                    <q-list separator dense>
                        <q-item
                            v-for="row in planRows"
                            :key="row.idx"
                            :clickable="!!row.child"
                            @click="row.child && onTaskClick(row.child.id)"
                        >
                            <q-item-section avatar>
                                <q-icon :name="rowIcon(row)" :color="rowColor(row)" size="20px" />
                            </q-item-section>
                            <q-item-section>
                                <q-item-label>{{ row.label }}</q-item-label>
                                <q-item-label caption lines="2">{{ richTextExcerpt(row.objective ?? '') }}</q-item-label>
                            </q-item-section>
                            <q-item-section side>
                                <div class="row items-center q-gutter-x-sm">
                                    <span v-if="row.child?.cost" class="text-caption text-grey">${{ row.child.cost.toFixed(4) }}</span>
                                    <StatusBadge
                                        v-if="row.child"
                                        :tone="getTaskStatusTone(row.child.status)"
                                        :label="t(`task.status.${row.child.status}`)"
                                    />
                                    <StatusBadge
                                        v-if="row.child && pauseBadge(row.child)"
                                        :tone="pauseBadge(row.child)!.tone"
                                        :label="$t(pauseBadge(row.child)!.labelKey)"
                                        :icon="pauseBadge(row.child)!.icon"
                                    />
                                    <StatusBadge
                                        v-if="!row.child"
                                        tone="neutral"
                                        :label="$t('task.detail.stepPending')"
                                    />
                                    <q-icon v-if="row.child" name="chevron_right" color="grey-6" />
                                </div>
                            </q-item-section>
                        </q-item>
                    </q-list>
                </q-card-section>
            </q-card>

            <!-- Dispatch Block (Expandable) -->
            <DispatchResultComponent
                v-if="executionExpected"
                :dispatch-result="task.dispatch_result || null"
            />

            <!-- Expandable planner block between dispatch and execution. -->
            <PlannerResultComponent
                v-if="executionExpected"
                :plan="task.plan || null"
                :status="task.status"
                :planning="task.status === 'PLAN' && working"
            />

            <BriefingResultComponent
                v-if="executionExpected && (task.effort === 'high' || task.briefing_result || task.status === 'BRIEFING')"
                :briefing-result="task.briefing_result || null"
                :briefing="task.status === 'BRIEFING' && working"
            />

            <!-- Expandable execution trace, visible from EXEC start with live feedback. -->
            <ExecutionResultComponent
                :execution-result="executionResultForDisplay"
                :running="task.status === 'EXEC' && working"
                :suspended="!terminalStatuses.has(task.status) && (task.paused || ['PAUSED', 'WAITING'].includes(activitySnapshots[task.id]?.operational.operational_state ?? ''))"
                :feedback="task.feedback || null"
                :task-id="task.id"
                :agent-id="task.agent_id"
            >
                <template #detailed-state>
                    <q-card tag="section" flat bordered class="task-overview-block q-pa-sm" :aria-label="$t('task.detail.detailedState')">
                        <h3 class="text-subtitle2 q-mt-none q-mb-sm text-primary">
                            <q-icon name="monitor_heart" size="xs" class="q-mr-xs" />
                            {{ $t('task.detail.detailedState') }}
                        </h3>
                        <TaskActivitySummary
                            :activity="activitySnapshots[task.id]"
                            :unavailable="activityUnavailable"
                            :show-last-activity="false"
                            show-provenance
                        />
                    </q-card>
                </template>
            </ExecutionResultComponent>

        </q-card-section>
    </q-card>

    <!-- Loading state -->
    <q-card v-else-if="loading" class="task-detail flex flex-center" flat bordered>
        <q-card-section>
            <q-spinner color="primary" size="3em" />
            <div class="text-grey q-mt-sm">{{ $t('task.detail.loading') }}</div>
        </q-card-section>
    </q-card>

    <!-- Empty state -->
    <div v-else class="flex flex-center q-pa-xl text-grey">
        <q-icon name="task_alt" size="64px" class="q-mb-md" />
        <div class="text-h6">{{ $t('task.detail.selectTask') }}</div>
        <div class="text-caption">{{ $t('task.detail.selectTaskHint') }}</div>
    </div>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { EditorialContent, richTextExcerpt } from '@/core/util'
import { computed, reactive, ref, watch } from 'vue'
import { useInterval, useQuasar } from 'quasar'
import type { AIResult, Task, TaskContextCapsule, TaskContextKind, TaskFull } from '../types'
import { taskService } from '../services/taskService'
import {
  getTaskStatusIcon,
  getTaskStatusColor,
  getTaskOperationalColor,
  getTaskOperationalIcon,
  getTaskStatusTone,
  isUserPaused,
  pauseBadge,
  shouldAnimateTaskStatus
} from '../services/taskStatusService'
import { usePrivilegeStore } from '@/core/authorize'
import { privileges } from '@/core/authorize'
import { useTaskStore } from '../stores/taskStore'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import { agentService, type Agent } from '@/app/agent/services/agentService'
import { authService, type User } from '@/core/user/services/authService'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { StatusBadge } from '@/core/util'

import DispatchResultComponent from './DispatchResult.vue'
import PlannerResultComponent from './PlannerResult.vue'
import BriefingResultComponent from './BriefingResult.vue'
import ExecutionResultComponent from './ExecutionResult.vue'
import Markdown from '@/core/util/components/Markdown.vue'
import TaskLabCaptureMenu from '@/app/lab/components/TaskLabCaptureMenu.vue'
import { hasAnyPrivilege, labSectionPrivileges } from '@/app/lab'
import TopicAssignmentEditor from '@/app/topic/components/TopicAssignmentEditor.vue'
import { mergeTaskSnapshot } from '../taskSnapshot'
import { useTaskActivity } from '../useTaskActivity'
import TaskActivitySummary from './TaskActivitySummary.vue'

const $q = useQuasar()
const { registerInterval } = useInterval()
const { t, locale } = useI18n()

// Task store
const taskStore = useTaskStore()
const agentStore = useAgentStore()

// Privileges
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.TASK_EDIT))
const canEditLab = computed(() => hasAnyPrivilege(privilegeStore.hasPrivilege, [
    labSectionPrivileges.dispatcher[1],
    labSectionPrivileges.briefing[1],
    labSectionPrivileges.planner[1],
    labSectionPrivileges.task_executor[1],
]))

const terminalStatuses = new Set(['SUCCESS', 'ERROR'])
// RUN advances a fresh task or one waiting on internal coordination, planning, or
// briefing. It is unavailable for user-paused and terminal tasks.
const canRun = computed(() => {
    if (!task.value) return false
    if (!executionExpected.value) return false
    return !isUserPaused(task.value) && !terminalStatuses.has(task.value.status)
        && (task.value.status === 'CREATE' || task.value.paused)
})
// PAUSE is available for every live task that is not already user-paused.
const canPause = computed(() => {
    if (!task.value) return false
    if (!executionExpected.value) return false
    return !isUserPaused(task.value) && !terminalStatuses.has(task.value.status)
})
// RESUME is available only for user-paused tasks.
const canResume = computed(() => {
    if (!task.value) return false
    if (!executionExpected.value) return false
    return isUserPaused(task.value) && !terminalStatuses.has(task.value.status)
})
const canForceTerminate = computed(() => {
    return Boolean(task.value && !terminalStatuses.has(task.value.status))
})
const canRetry = computed(() => task.value?.status === 'ERROR')
// Distinguish user pauses from internal waiting states in the status badge.
const pauseState = computed(() => (task.value ? pauseBadge(task.value) : null))
const running = ref(false)
const pausing = ref(false)
const forceTerminating = ref(false)
const retrying = ref(false)
const topicSaving = ref(false)

interface DeliveryRecovery {
    status?: string
    filename?: string
    destination?: string
    child_task_id?: string
    tool?: string
}

const deliveryRecovery = computed<DeliveryRecovery | null>(() => {
    const marker = task.value?.data?.delivery_recovery
    return marker && typeof marker === 'object' ? marker as DeliveryRecovery : null
})
const isDeliveryRecoveryReady = computed(
    () => deliveryRecovery.value?.status === 'ready'
)

async function onRun() {
    if (!task.value) return
    running.value = true
    try {
        await taskStore.runTask(task.value.id)
        $q.notify({
            message: t('task.notify.runSuccess'),
            color: 'positive',
            icon: 'check_circle',
            timeout: 3000,
            position: 'top'
        })
    } catch (err) {
        console.error('Failed to run task:', err)
        $q.notify({
            message: t('task.notify.runError'),
            color: 'negative',
            icon: 'error',
            timeout: 5000,
            position: 'top'
        })
    } finally {
        running.value = false
    }
}

async function onPause() {
    if (!task.value) return
    pausing.value = true
    try {
        const pausedTask = await taskStore.pauseTask(task.value.id)
        task.value = mergeTaskSnapshot(task.value, pausedTask as TaskFull)
        $q.notify({
            message: t('task.notify.pauseSuccess'),
            color: 'positive',
            icon: 'pause_circle',
            timeout: 3000,
            position: 'top'
        })
    } catch (err) {
        console.error('Failed to pause task:', err)
        $q.notify({
            message: apiErrorDetail(err) || t('task.notify.pauseError'),
            color: 'negative',
            icon: 'error',
            timeout: 5000,
            position: 'top'
        })
    } finally {
        pausing.value = false
    }
}

async function onRetry() {
    if (!task.value || retrying.value) return
    retrying.value = true
    const deliveryOnly = isDeliveryRecoveryReady.value
    try {
        const retried = await taskStore.retryTask(task.value.id, task.value.revision)
        // The retry response is the committed transition. Apply it immediately so
        // the stale failure disappears before the scheduler's next WebSocket event.
        task.value = mergeTaskSnapshot(task.value, retried as TaskFull)
        $q.notify({
            message: t(
                deliveryOnly
                    ? 'task.notify.deliveryRetrySuccess'
                    : 'task.notify.retrySuccess'
            ),
            color: 'positive',
            icon: 'replay',
            timeout: 3000,
            position: 'top'
        })
    } catch (err) {
        console.error('Failed to retry task:', err)
        $q.notify({
            message: t('task.notify.retryError'),
            color: 'negative',
            icon: 'error',
            timeout: 5000,
            position: 'top'
        })
    } finally {
        retrying.value = false
    }
}

async function onResume() {
    if (!task.value) return
    pausing.value = true
    try {
        await taskStore.resumeTask(task.value.id)
        $q.notify({
            message: t('task.notify.resumeSuccess'),
            color: 'positive',
            icon: 'play_circle',
            timeout: 3000,
            position: 'top'
        })
    } catch (err) {
        console.error('Failed to resume task:', err)
        $q.notify({
            message: t('task.notify.resumeError'),
            color: 'negative',
            icon: 'error',
            timeout: 5000,
            position: 'top'
        })
    } finally {
        pausing.value = false
    }
}

async function saveTopic(topicId: string | null): Promise<void> {
    if (!task.value || topicSaving.value || !canEdit.value) return
    topicSaving.value = true
    try {
        const updated = await taskStore.updateTask(task.value.id, {
            expected_revision: task.value.revision,
            topic_id: topicId,
        })
        task.value = mergeTaskSnapshot(task.value, updated as TaskFull)
        $q.notify({
            message: t('topic.assignmentUpdated'),
            color: 'positive',
            icon: 'folder',
            timeout: 2500,
            position: 'top',
        })
    } catch (err) {
        console.error('Failed to update task topic:', err)
        $q.notify({
            message: t('topic.assignmentUpdateError'),
            color: 'negative',
            icon: 'error',
            timeout: 4000,
            position: 'top',
        })
    } finally {
        topicSaving.value = false
    }
}

function confirmForceTerminate() {
    if (!task.value || forceTerminating.value) return
    showConfirmationDialog({
        title: t('task.detail.forceTerminateConfirmTitle'),
        message: t('task.detail.forceTerminateConfirmMessage', { label: task.value.label }),
        cancel: true,
        ok: {
            label: t('task.detail.forceTerminateConfirmAction'),
            color: 'negative'
        },
        focus: 'cancel'
    }).onOk(() => {
        void onForceTerminate()
    })
}

async function onForceTerminate() {
    if (!task.value) return
    forceTerminating.value = true
    try {
        await taskStore.forceTerminateTask(task.value.id, task.value.revision)
        $q.notify({
            message: t('task.notify.forceTerminateSuccess'),
            color: 'positive',
            icon: 'check_circle',
            timeout: 4000,
            position: 'top'
        })
    } catch (err) {
        console.error('Failed to force-terminate task:', err)
        $q.notify({
            message: t('task.notify.forceTerminateError'),
            color: 'negative',
            icon: 'error',
            timeout: 5000,
            position: 'top'
        })
    } finally {
        forceTerminating.value = false
    }
}

// System tasks were removed with the legacy task tree.
const isSystemTask = computed(() => false)

// Export JSON directly to the clipboard.
const exportableTaskJson = computed(() => {
    if (!task.value) return ''
    try {
        return JSON.stringify(task.value, null, 2)
    } catch {
        return '{}'
    }
})

async function copyJsonToClipboard() {
    try {
        await navigator.clipboard.writeText(exportableTaskJson.value)
        // Keep the confirmation unobtrusive.
        $q.notify({
            message: t('task.notify.jsonCopied'),
            color: 'positive',
            icon: 'check_circle',
            timeout: 2000,
            position: 'top'
        })
    } catch (err) {
        console.error('Failed to copy JSON:', err)
        $q.notify({
            message: t('task.notify.copyError'),
            color: 'negative',
            icon: 'error',
            timeout: 3000,
            position: 'top'
        })
    }
}

async function copyTaskIdToClipboard() {
    if (!task.value) return
    try {
        await navigator.clipboard.writeText(task.value.id)
        $q.notify({
            message: t('task.notify.idCopied'),
            color: 'positive',
            icon: 'check_circle',
            timeout: 1500,
            position: 'top'
        })
    } catch (err) {
        console.error('Failed to copy Task identifier:', err)
        $q.notify({
            message: t('task.notify.copyError'),
            color: 'negative',
            icon: 'error',
            timeout: 3000,
            position: 'top'
        })
    }
}

// Date formatting helper
function formatDate(dateStr: string | null | undefined): string {
    if (!dateStr) return '-'
    const date = new Date(dateStr)
    return date.toLocaleString(locale.value, {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    })
}

const props = defineProps<{
    taskId: string | null
}>()

const emit = defineEmits<{
    'refresh': []
    'delete': [task: TaskFull]
    'task-change': [taskId: string]
}>()

// Navigate to a parent or child task.
function onTaskClick(taskId: string) {
    emit('task-change', taskId)
}

function onDelete() {
    if (!task.value) return
    emit('delete', task.value)
}

// Task loading state
const task = ref<TaskFull | null>(null)
const { snapshots: activitySnapshots, unavailable: activityUnavailable, resultFor } = useTaskActivity(() => task.value ? [task.value] : [])
const executionResultForDisplay = computed<AIResult | null>(() => task.value ? resultFor(task.value) : null)
const working = computed(() => Boolean(task.value && shouldAnimateTaskStatus({ ...task.value,
    operationalState: activitySnapshots.value[task.value.id]?.operational.operational_state })))
const currentTaskAgent = ref<Agent | null>(null)
const requesterAgent = ref<Agent | null>(null)
const creatorUser = ref<User | null>(null)
const avatarUrls = reactive<Record<number, string>>({})
const loading = ref(false)
const error = ref<string | null>(null)
let loadTaskRequest = 0
let liveRefreshInFlight = false
const feedbackContent = computed(() => task.value?.feedback?.trim() || '')
const contextCapsule = computed<TaskContextCapsule | null>(() => {
    const raw = task.value?.data?.interlocutor_context
    if (!raw || typeof raw !== 'object') return null
    const capsule = raw as Partial<TaskContextCapsule>
    if (
        capsule.version !== 1
        || typeof capsule.contact_memory_item_id !== 'string'
        || !Array.isArray(capsule.entries)
        || typeof capsule.created_at !== 'string'
    ) return null
    return capsule as TaskContextCapsule
})

function contextKindIcon(kind: TaskContextKind): string {
    return {
        conversation: 'forum',
        task: 'task_alt',
        resource: 'description',
        memory: 'psychology',
    }[kind]
}
const subtaskEffort = computed(() => task.value?.parent_id && task.value.effort ? task.value.effort : null)
const isAwaitCoordinationTask = computed(() => {
    const current = task.value
    if (!current) return false
    return current.coordination_type === 'await_reply'
        || current.is_coordination === true
        || Boolean((current.data as Record<string, unknown> | undefined)?.awaiting_reply)
})
const executionExpected = computed(() => {
    if (!task.value) return true
    if (task.value.execution_expected === false) return false
    return !isAwaitCoordinationTask.value
})
const awaitPeerLabel = computed(() => {
    const marker = (task.value?.data as Record<string, unknown> | undefined)?.awaiting_reply
    if (!marker || typeof marker !== 'object') return t('task.detail.waitingColleague')
    const data = marker as Record<string, unknown>
    return String(data.peer_display || data.peer_user_id || t('task.detail.waitingColleague'))
})

function getEffortColor(effort: string): string {
    switch (effort) {
        case 'high': return 'deep-orange'
        case 'standard': return 'blue-grey'
        default: return 'grey'
    }
}

// Planner-defined steps and cursor-based progress.
const planSteps = computed<Array<{ objective?: string; label?: string }>>(
  () => (task.value?.plan?.steps as Array<{ objective?: string; label?: string }>) ?? []
)
const planCursor = computed(() => Number(task.value?.plan?.cursor ?? 0))
const planDoneCount = computed(() => {
  if (task.value?.status === 'SUCCESS') return planRows.value.length
  return displayChildren.value.filter(c => c.status === 'SUCCESS').length
})
function planStepState(idx: number): 'done' | 'current' | 'failed' | 'pending' {
  if (task.value?.status === 'SUCCESS') return 'done'
  if (idx < planCursor.value) return 'done'
  if (idx === planCursor.value) return task.value?.status === 'ERROR' ? 'failed' : 'current'
  return 'pending'
}
function planStepIcon(idx: number): string {
  const state = planStepState(idx)
  return state === 'done' ? 'check_circle'
    : state === 'failed' ? 'error'
    : state === 'current' ? 'hourglass_top'
    : 'radio_button_unchecked'
}
function planStepColor(idx: number): string {
  const state = planStepState(idx)
  return state === 'done' ? 'positive'
    : state === 'failed' ? 'negative'
    : state === 'current' ? 'primary'
    : 'grey-5'
}

// Persisted child tasks and parent task used for tree navigation.
const children = ref<Task[]>([])
const parentTask = ref<Task | null>(null)
let relationRequest = 0

// Prefer the live WebSocket-updated store version when available.
const displayChildren = computed<Task[]>(() =>
  children.value.map(c => taskStore.recentTasks.find(rt => rt.id === c.id) ?? c)
)
const activeReplyWaits = computed(() => displayChildren.value.flatMap((child) => {
  if (terminalStatuses.has(child.status)) return []
  const marker = child.data?.awaiting_reply
  if (!marker || typeof marker !== 'object') return []
  const data = marker as Record<string, unknown>
  return [{
    id: child.id,
    question: child.objective?.trim() || '',
    peer: String(data.peer_display || data.peer_user_id || data.process_label || t('task.detail.waitingColleague')),
    deadline: data.deadline ? String(data.deadline) : null,
  }]
}))
const resolvedByTask = computed<Task | null>(() => {
  if (!task.value) return null
  const resolvedId = task.value.resolved_by_task_id
  if (resolvedId) {
    const byId = displayChildren.value.find(c => c.id === resolvedId)
    if (byId) return byId
  }
  return displayChildren.value.find(c => {
    const data = c.data as Record<string, unknown> | undefined
    return data?.resolves_await === task.value?.id
  }) ?? null
})

interface PlanRow { idx: number; label: string; objective?: string; child?: Task }
// Build one ordered view linking each plan step to its persisted child when present.
// Otherwise show a pending step; without a plan, list children directly.
const planRows = computed<PlanRow[]>(() => {
  const byStep = new Map<number, Task>()
  for (const c of displayChildren.value) {
    const step = Number((c.data as Record<string, unknown> | undefined)?.plan_step ?? -1)
    if (step >= 0) byStep.set(step, c)
  }
  if (planSteps.value.length) {
    return planSteps.value.map((s, idx) => ({
      idx,
      label: s.label || t('task.detail.planStep', { n: idx + 1 }),
      objective: s.objective,
      child: byStep.get(idx),
    }))
  }
  return displayChildren.value.map((c, idx) => ({
    idx, label: c.label, objective: c.objective ?? undefined, child: c,
  }))
})

function rowIcon(row: PlanRow): string {
  return row.child ? getTaskStatusIcon(row.child.status) : planStepIcon(row.idx)
}
function rowColor(row: PlanRow): string {
  return row.child ? getTaskStatusColor(row.child.status) : planStepColor(row.idx)
}

// Load child and parent tasks for navigation.
async function loadRelations(t: TaskFull | null): Promise<void> {
  const request = ++relationRequest
  if (!t) {
    children.value = []
    parentTask.value = null
    return
  }
  const taskId = t.id
  try {
    const loadedChildren = await taskService.getChildren(taskId)
    if (request !== relationRequest || task.value?.id !== taskId) return
    children.value = loadedChildren.map((child) => {
      const live = taskStore.latestTaskUpdate?.id === child.id
        ? taskStore.latestTaskUpdate
        : null
      return live ? mergeTaskSnapshot(child, live) : child
    })
  } catch (err) {
    if (request !== relationRequest || task.value?.id !== taskId) return
    console.error('Failed to load task children:', err)
    children.value = []
  }
  if (t.parent_id) {
    try {
      const loadedParent = (await taskService.getById(t.parent_id)) as unknown as Task
      if (request !== relationRequest || task.value?.id !== taskId) return
      parentTask.value = loadedParent
    } catch (err) {
      if (request !== relationRequest || task.value?.id !== taskId) return
      console.error('Failed to load parent task:', err)
      parentTask.value = null
    }
  } else {
    parentTask.value = null
  }
}
const requesterVisible = computed(() => Boolean(task.value?.requester_agent_id != null || task.value?.created_by != null))
const assignedAgentName = computed(() => agentDisplayName(currentTaskAgent.value, task.value?.agent_id))
const assignedAgentAvatarUrl = computed(() => agentAvatarUrl(currentTaskAgent.value))
const requesterName = computed(() => {
    if (task.value?.requester_agent_id != null) {
        return agentDisplayName(requesterAgent.value, task.value.requester_agent_id)
    }
    return userDisplayName(creatorUser.value, task.value?.created_by)
})
const requesterAgentAvatarUrl = computed(() => agentAvatarUrl(requesterAgent.value))

function agentAvatarUrl(agent: Agent | null): string | undefined {
    if (!agent?.has_avatar) return undefined
    return avatarUrls[agent.id]
}

function agentDisplayName(agent: Agent | null, fallbackId?: number | null): string {
    if (agent) {
        return `${agent.first_name} ${agent.last_name}`.trim()
    }
    if (fallbackId != null) return t('task.list.agentId', { id: fallbackId })
    return t('task.list.noAgent')
}

function userDisplayName(user: User | null, fallbackId?: number | null): string {
    if (user) return user.display_name || user.email
    if (fallbackId != null) return t('task.detail.userId', { id: fallbackId })
    return t('task.list.noAgent')
}

async function resolveAgent(id: number | null | undefined, fallback?: Agent | null): Promise<Agent | null> {
    if (id == null) return null
    if (fallback?.id === id) return fallback
    const cached = agentStore.agents.find(agent => agent.id === id)
    if (cached) return cached
    try {
        const response = await agentService.getAgent(id)
        return response.data
    } catch (err) {
        console.error('Failed to load task requester agent:', err)
        return null
    }
}

async function loadAgentAvatar(agent: Agent | null): Promise<void> {
    if (!agent?.has_avatar || avatarUrls[agent.id]) return
    try {
        avatarUrls[agent.id] = await agentService.getAvatarBlobUrl(agent.id)
    } catch (err) {
        console.error(`Failed to load avatar for agent ${agent.id}:`, err)
    }
}

async function resolveUser(id: number | null | undefined): Promise<User | null> {
    if (id == null) return null
    try {
        return await authService.getUser(id)
    } catch (err) {
        console.error('Failed to load task creator user:', err)
        return null
    }
}

// Load the task and its related agents.
async function loadTask() {
    const request = ++loadTaskRequest
    if (!props.taskId) {
        task.value = null
        currentTaskAgent.value = null
        requesterAgent.value = null
        creatorUser.value = null
        return
    }
    const taskId = props.taskId

    loading.value = true
    error.value = null

    try {
        const [fullTask, { agent }] = await Promise.all([
            taskService.getFull(taskId),
            taskStore.fetchTaskByIdWithAgent(taskId)
        ])
        if (request !== loadTaskRequest || props.taskId !== taskId) return
        const liveTask = taskStore.currentTask?.id === taskId ? taskStore.currentTask : null
        let mergedTask = liveTask
            ? mergeTaskSnapshot(fullTask, liveTask as TaskFull)
            : fullTask
        if (taskStore.latestTaskUpdate?.id === taskId) {
            mergedTask = mergeTaskSnapshot(mergedTask, taskStore.latestTaskUpdate as TaskFull)
        }
        task.value = mergedTask
        currentTaskAgent.value = agent || null
        requesterAgent.value = await resolveAgent(mergedTask.requester_agent_id, agent || null)
        creatorUser.value = mergedTask.requester_agent_id == null ? await resolveUser(mergedTask.created_by) : null
        if (request !== loadTaskRequest || props.taskId !== taskId) return
        await Promise.all([
            loadAgentAvatar(currentTaskAgent.value),
            loadAgentAvatar(requesterAgent.value)
        ])
        if (request !== loadTaskRequest || props.taskId !== taskId) return
        void loadRelations(mergedTask)
    } catch (err) {
        if (request !== loadTaskRequest || props.taskId !== taskId) return
        error.value = err instanceof Error ? err.message : t('task.notify.loadError')
        console.error('Failed to load task:', err)
    } finally {
        if (request === loadTaskRequest) loading.value = false
    }
}

async function reconcileLiveTask(): Promise<void> {
    const current = task.value
    if (
        liveRefreshInFlight
        || !current
        || current.id !== props.taskId
        || terminalStatuses.has(current.status)
    ) return

    liveRefreshInFlight = true
    const taskId = current.id
    try {
        const snapshot = await taskService.getFull(taskId)
        if (task.value?.id !== taskId || props.taskId !== taskId) return
        task.value = mergeTaskSnapshot(task.value, snapshot)
        taskStore.applyTaskSnapshot(snapshot)
        // Child transitions are separate durable writes and do not necessarily
        // bump the selected parent's revision.
        void loadRelations(task.value)
    } catch (err) {
        // WebSocket remains the primary path. A transient reconciliation error
        // should not replace an already rendered task with an error screen.
        console.warn('Failed to reconcile live task:', err)
    } finally {
        liveRefreshInFlight = false
    }
}

// Watch for taskId changes
watch(() => props.taskId, () => {
    loadTask()
}, { immediate: true })

// The store updates currentTask on each task.update WebSocket event. Its payload
// serializes the complete Task schema, equivalent to TaskFull, so merge changes
// into the displayed task without fetching it again.
watch(() => taskStore.currentTask, (updated) => {
    if (updated && task.value && updated.id === task.value.id) {
        task.value = mergeTaskSnapshot(task.value, updated as TaskFull)
    }
})

// Apply child and parent updates immediately even when they are outside the
// currently filtered/paginated task list.
watch(() => taskStore.latestTaskUpdate, (updated) => {
    if (!updated || !task.value) return
    if (updated.id === task.value.id) {
        task.value = mergeTaskSnapshot(task.value, updated as TaskFull)
        return
    }
    const childIndex = children.value.findIndex(child => child.id === updated.id)
    if (childIndex >= 0) {
        const next = [...children.value]
        next[childIndex] = mergeTaskSnapshot(next[childIndex], updated)
        children.value = next
    } else if (updated.parent_id === task.value.id) {
        void loadRelations(task.value)
    }
    if (parentTask.value?.id === updated.id) {
        parentTask.value = mergeTaskSnapshot(parentTask.value, updated)
    }
}, { flush: 'sync' })

// Socket.IO events are intentionally ephemeral. Reconcile active details as a
// safety net for brief disconnects and events emitted during initial loading.
registerInterval(() => void reconcileLiveTask(), 5000)

// Refresh child statuses when the plan cursor advances.
watch(() => Number(task.value?.plan?.cursor ?? -1), (next, prev) => {
    if (next !== prev && task.value) void loadRelations(task.value)
})

// Initial materialization creates the whole tree at once. WebSocket events may
// arrive after the detail view's first load, so reload relations when new children
// appear in the live list.
watch(
    () => taskStore.recentTasks.filter(c => c.parent_id === task.value?.id).map(c => c.id).join(','),
    (next, prev) => {
        if (next !== prev && task.value) void loadRelations(task.value)
    }
)


// Delegate status presentation to the shared service.


function getHeaderBgClass(status: string): string {
    // Background colors by status.
    const bgClasses: Record<string, string> = {
        'CREATE': 'bg-grey-1',
        'DISPATCH': 'bg-purple-1',
        'BRIEFING': 'bg-amber-1',
        'EXEC': 'bg-blue-1',
        'PLAN': 'bg-teal-1',
        'SUCCESS': 'bg-positive-1',
        'ERROR': 'bg-negative-1'
    }
    return bgClasses[status] || 'bg-grey-1'
}

</script>

<style scoped>
.task-detail {
    min-height: 400px;
}

.task-overview-block {
    min-width: 0;
}

.task-overview .task-overview-topic {
    padding: 0;
}

.task-header-row {
    gap: 8px;
}

.task-id {
    font-family: monospace;
    overflow-wrap: anywhere;
}

.task-header-agent {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    max-width: 260px;
    padding: 2px 8px 2px 2px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.72);
    color: #3c4043;
    font-size: 12px;
    line-height: 1.2;
}

.task-header-agent-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

body.body--dark .task-header-agent {
    background: rgba(0, 0, 0, 0.22);
    color: #f5f5f5;
}

.task-metadata {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
}

.task-metadata-item {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
}

.task-metadata-avatar {
    flex: 0 0 32px;
}

.task-metadata-label {
    color: #667085;
    font-size: 12px;
    line-height: 1.2;
}

body.body--dark .task-metadata-label {
    color: #98a2b8;
}

.context-capsule-excerpt {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

.context-capsule-reference {
    font-family: monospace;
    overflow-wrap: anywhere;
}

.bg-grey-1 {
    background-color: rgba(158, 158, 158, 0.1);
}

.bg-blue-1 {
    background-color: rgba(25, 118, 210, 0.1);
}

.bg-info-1 {
    background-color: rgba(0, 123, 255, 0.1);
}

.bg-positive-1 {
    background-color: rgba(33, 186, 69, 0.1);
}

.bg-negative-1 {
    background-color: rgba(193, 0, 21, 0.1);
}

.bg-purple-1 {
    background-color: rgba(156, 39, 176, 0.1);
}

.bg-teal-1 {
    background-color: rgba(0, 150, 136, 0.1);
}

/* Hover effects for clickable task items */
.hoverable-card {
    transition: all 0.2s ease;
}

.hoverable-card:hover {
    background-color: rgba(25, 118, 210, 0.05);
    border-color: #1976d2;
}

.hoverable-item {
    transition: all 0.2s ease;
}

.hoverable-item:hover {
    background-color: rgba(25, 118, 210, 0.05);
}

/* Preformatted result display */
.result-pre {
    white-space: pre-wrap;
    word-break: break-word;
    margin: 0;
    font-family: monospace;
}
</style>
