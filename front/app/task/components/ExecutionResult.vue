<template>
    <q-expansion-item v-if="displayedExecutionResult || running || hasLlmCallSource" icon="terminal" :label="$t('task.execution.title')"
        :model-value="embedded ? true : undefined" default-opened
        :header-class="embedded ? 'execution-result-header--hidden' : 'text-deep-orange text-subtitle2'" class="exec-expansion q-mt-md" dense toggle-indicator>
        <template v-slot:header>
            <q-item-section avatar>
                <q-icon name="terminal" color="deep-orange" />
            </q-item-section>
            <q-item-section>
                <q-item-label>
                    <div class="row items-center q-gutter-x-sm">
                        <span>{{ $t('task.execution.title') }}</span>
                        <q-badge
                            v-if="runtimeRunId"
                            color="grey-6"
                            outline
                            class="runtime-run-badge cursor-pointer text-weight-regular"
                            role="button"
                            tabindex="0"
                            :aria-label="$t('task.execution.copyRunId')"
                            @click.stop="copyRuntimeRunId"
                            @keydown.enter.stop.prevent="copyRuntimeRunId"
                            @keydown.space.stop.prevent="copyRuntimeRunId"
                        >
                            {{ $t('task.execution.runtimeRun') }} {{ runtimeRunId }}
                            <q-icon name="content_copy" size="11px" class="q-ml-xs" />
                            <q-tooltip>{{ $t('task.execution.copyRunId') }}</q-tooltip>
                        </q-badge>
                    </div>
                </q-item-label>
                <q-item-label v-if="running && feedback" caption class="text-deep-orange">
                    {{ feedback }}
                </q-item-label>
            </q-item-section>
            <q-item-section side v-if="displayedExecutionResult && !running">
                <div class="row q-gutter-xs">
                    <StatusBadge
                        v-if="!suspended"
                        :tone="executionSucceeded ? 'success' : 'error'"
                        :icon="executionSucceeded ? 'check_circle' : 'error'"
                        :label="executionSucceeded ? $t('task.dispatch.success') : $t('task.dispatch.failure')"
                    />
                    <q-badge color="blue" size="sm">
                        <q-icon name="timer" size="xs" class="q-mr-xs" />
                        {{ formatExecutionTime(displayedExecutionResult.execution_time) }}
                    </q-badge>
                    <q-badge v-if="displayedExecutionResult.cost > 0" color="purple" size="sm">
                        <q-icon name="attach_money" size="xs" class="q-mr-xs" />
                        {{ formatCostShort(displayedExecutionResult.cost) }}
                    </q-badge>
                </div>
            </q-item-section>
            <q-item-section side v-else-if="running">
                <q-spinner-dots color="deep-orange" size="24px" />
            </q-item-section>
        </template>

        <q-card flat bordered class="execution-result-shell q-mt-sm">
            <q-card-section>
                <q-tabs v-model="activeTab" dense class="text-grey" active-color="primary" indicator-color="primary" align="left" narrow-indicator>
                    <q-tab name="trace">
                        <div class="row items-center no-wrap">
                            <q-icon name="hub" class="q-mr-xs" />
                            <span>{{ $t('task.execution.thoughtSteps') }}</span>
                        </div>
                    </q-tab>
                    <q-tab v-if="taskId" name="details">
                        <div class="row items-center no-wrap">
                            <q-icon name="info" class="q-mr-xs" />
                            <span>{{ $t('task.execution.details') }}</span>
                        </div>
                    </q-tab>
                    <q-tab v-if="showMemoryTab" name="memory">
                        <div class="row items-center no-wrap">
                            <q-icon name="database" class="q-mr-xs" />
                            <span>{{ $t('task.memory.tab', { count: memoryOperationCount }) }}</span>
                        </div>
                    </q-tab>
                    <q-tab v-if="!taskId && $slots.details" name="details">
                        <div class="row items-center no-wrap">
                            <q-icon name="info" class="q-mr-xs" />
                            <span>{{ $t('task.execution.details') }}</span>
                        </div>
                    </q-tab>
                    <q-tab name="prompt">
                        <div class="row items-center no-wrap">
                            <q-icon name="message" class="q-mr-xs" />
                            <span>{{ $t('task.dispatch.prompt') }}</span>
                        </div>
                    </q-tab>
                    <q-tab name="system-prompt">
                        <div class="row items-center no-wrap">
                            <q-icon name="settings" class="q-mr-xs" />
                            <span>{{ $t('task.dispatch.systemPrompt') }}</span>
                        </div>
                    </q-tab>
                    <q-tab v-if="hasLlmCallSource" name="llm-calls">
                        <div class="row items-center no-wrap">
                            <q-icon name="memory" class="q-mr-xs" />
                            <span>{{ $t('task.execution.llmCalls') }}</span>
                        </div>
                    </q-tab>
                </q-tabs>

                <q-separator />
                <q-tab-panels v-model="activeTab" animated>
                    <!-- Trace Tab -->
                    <q-tab-panel name="trace">
                        <div v-if="displayedMessages.length" class="trace-timeline">
                            <div
                                v-for="(step, index) in displayedMessages"
                                :key="stepKey(step, index)"
                                class="timeline-item"
                            >
                                <!-- Timeline connector -->
                                <div class="timeline-connector">
                                    <div class="timeline-dot" :class="'timeline-dot-' + stepKind(step)"></div>
                                    <div v-if="index < displayedMessages.length - 1" class="timeline-line"></div>
                                </div>

                                <!-- Content column: header + expanded content -->
                                <div class="timeline-content-col">
                                    <!-- Step header (always visible) -->
                                    <div class="timeline-header" @click="toggleStep(stepKey(step, index))">
                                        <div class="timeline-header-left">
                                            <q-icon :name="getStepIcon(step)" :color="getStepColor(step)" size="xs" class="q-mr-xs" />
                                            <span v-if="stepKind(step) === 'thinking'" class="tool-name text-body2">{{ $t('task.execution.thinking') }}</span>
                                            <span v-else-if="step.type === 'tool'" class="tool-name text-body2">{{ step.tool_name }}</span>
                                            <span v-else class="text-caption text-grey">{{ $t('task.execution.ai') }}</span>
                                        </div>
                                        <div class="timeline-header-right">
                                            <span class="text-caption text-grey q-mr-sm gt-sm">{{ truncateContent(step.content) }}</span>
                                            <StatusBadge
                                                v-if="step.type === 'tool' && stepKind(step) !== 'thinking'"
                                                :tone="step.success === false ? 'error' : 'success'"
                                                :icon="step.success === false ? 'error' : 'check_circle'"
                                                :label="step.success === false ? $t('task.dispatch.failure') : $t('task.dispatch.success')"
                                                class="q-mr-xs"
                                            />
                                            <q-badge v-if="step.execution_time !== undefined && step.execution_time > 0" color="blue" size="sm" class="q-mr-xs">
                                                <q-icon name="timer" size="xs" class="q-mr-xs" />
                                                {{ formatExecutionTime(step.execution_time) }}
                                            </q-badge>
                                            <q-badge v-if="step.cost !== undefined && step.cost > 0" color="purple" size="sm" class="q-mr-xs">
                                                <q-icon name="attach_money" size="xs" class="q-mr-xs" />
                                                {{ formatCostShort(step.cost) }}
                                            </q-badge>
                                            <q-icon :name="expandedSteps.has(stepKey(step, index)) ? 'expand_less' : 'expand_more'" size="xs" />
                                        </div>
                                    </div>

                                    <!-- Expanded content -->
                                    <q-slide-transition>
                                        <div v-show="expandedSteps.has(stepKey(step, index))" class="timeline-expanded">
                                            <!-- Text/Audio/Image/Video Step -->
                                            <q-card v-if="step.type !== 'tool'" flat bordered class="trace-card">
                                                <q-card-section class="q-py-xs q-px-sm">
                                                    <Markdown :content="step.content" />
                                                </q-card-section>
                                            </q-card>

                                            <!-- Tool Step -->
                                            <q-card v-else flat bordered class="trace-card tool-card"
                                                :class="{ 'thinking-card': stepKind(step) === 'thinking' }">
                                                <q-card-section class="q-py-xs q-px-sm">
                                                    <!-- Arguments Table -->
                                                    <q-table
                                                        v-if="step.tool_arguments && Object.keys(step.tool_arguments).length"
                                                        :rows="formatArgumentsToTable(step.tool_arguments)"
                                                        :columns="argumentColumns"
                                                        row-key="name"
                                                        flat
                                                        dense
                                                        bordered
                                                        hide-pagination
                                                        :pagination="{ rowsPerPage: 0 }"
                                                        class="arguments-table q-mb-xs"
                                                    >
                                                        <template v-slot:body-cell-name="props">
                                                            <td class="text-left">
                                                                <code class="argument-name">{{ props.value }}</code>
                                                            </td>
                                                        </template>
                                                        <template v-slot:body-cell-value="props">
                                                            <td class="text-left">
                                                                <code class="argument-value">{{ props.value }}</code>
                                                            </td>
                                                        </template>
                                                    </q-table>

                                                    <!-- Response -->
                                                    <Markdown :content="step.content" />
                                                </q-card-section>
                                            </q-card>
                                        </div>
                                    </q-slide-transition>
                                </div>
                            </div>
                        </div>
                        <div v-else class="trace-timeline">
                            <div class="timeline-item timeline-item--pending">
                                <div class="timeline-connector">
                                    <div class="timeline-dot timeline-dot-pending"></div>
                                </div>
                                <div class="timeline-content-col">
                                    <div class="timeline-header timeline-header--pending">
                                        <div class="timeline-header-left">
                                            <q-icon name="pending" color="grey-7" size="xs" class="q-mr-xs" />
                                            <span class="text-caption text-grey">
                                                {{ running
                                                    ? $t('task.execution.starting')
                                                    : $t('task.execution.noTrace') }}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </q-tab-panel>
                    <q-tab-panel v-if="taskId" name="details">
                        <slot name="detailed-state" />
                        <q-card flat bordered class="q-pa-sm q-mt-md">
                            <h3 class="text-subtitle2 q-mt-none q-mb-sm text-primary">
                                <q-icon name="account_balance_wallet" size="xs" class="q-mr-xs" />
                                {{ $t('task.execution.budget') }}
                            </h3>
                            <TaskBudget :task-id="taskId" />
                        </q-card>
                    </q-tab-panel>
                    <q-tab-panel v-if="showMemoryTab" name="memory">
                        <ExecutionMemoryPanel
                            :agent-id="memoryAgentId"
                            :context="memoryContext"
                            :calls="memoryCalls"
                        />
                    </q-tab-panel>

                    <q-tab-panel v-if="!taskId && $slots.details" name="details">
                        <slot name="details" />
                    </q-tab-panel>

                    <!-- Prompt Tab -->
                    <q-tab-panel name="prompt">
                        <div v-if="displayedPrompt" class="text-body2 q-pa-sm rounded-borders">
                            <Markdown :content="displayedPrompt" />
                        </div>
                        <div v-else class="text-grey text-center q-pa-md">
                            {{ $t('task.dispatch.noPrompt') }}
                        </div>
                    </q-tab-panel>

                    <!-- System Prompt Tab -->
                    <q-tab-panel name="system-prompt">
                        <div v-if="displayedSystemPrompt" class="text-body2 q-pa-sm rounded-borders">
                            <pre style="white-space: pre-wrap; overflow-wrap: anywhere">{{ displayedSystemPrompt }}</pre>
                        </div>
                        <div v-else class="text-grey text-center q-pa-md">
                            {{ $t('task.dispatch.noSystemPrompt') }}
                        </div>
                    </q-tab-panel>

                    <!-- LLM Calls Tab -->
                    <q-tab-panel v-if="hasLlmCallSource" name="llm-calls">
                        <LlmCalls
                            :task-id="taskId"
                            :external-calls="llmCalls"
                            :loading="llmCallsLoading"
                            :error="llmCallsError"
                        />
                    </q-tab-panel>

                </q-tab-panels>
            </q-card-section>
        </q-card>
    </q-expansion-item>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { copyToClipboard, useQuasar } from 'quasar'
import type { AIMessage, ExecutionResult } from '../types'
import type { LLMCall } from '@/app/llm/types'
import { callExecutionResult } from '@/app/llm/presentation'
import Markdown from '@/core/util/components/Markdown.vue'
import { StatusBadge } from '@/core/util'
import LlmCalls from '@/app/llm/components/LlmCalls.vue'
import ExecutionMemoryPanel from './ExecutionMemoryPanel.vue'
import TaskBudget from './TaskBudget.vue'

const props = withDefaults(defineProps<{
    executionResult: ExecutionResult | null
    /** Durable domain outcome, authoritative over failed intermediate LLM attempts. */
    executionSuccess?: boolean
    /** Whether the task is running; show this block immediately with live feedback. */
    running?: boolean
    /** A suspended Task has no business outcome yet, even if its transport was cancelled. */
    suspended?: boolean
    feedback?: string | null
    /** Task ID enabling the WebSocket-fed LLM calls tab. */
    taskId?: string
    /** Preloaded calls for non-Task executions such as conversation rounds. */
    llmCalls?: LLMCall[]
    llmCallsLoading?: boolean
    llmCallsError?: string
    /** Expose the memory tab on conversation and voice surfaces. */
    showMemory?: boolean
    /** Agent whose governed memory was available to this execution. */
    agentId?: number | null
    /** Human-readable speakers used when reconstructing provider prompts. */
    agentName?: string
    userName?: string
    /** Hide the redundant outer execution header when embedded in another disclosure. */
    embedded?: boolean
}>(), { executionSuccess: undefined })

const activeTab = ref('trace')
const expandedSteps = ref<Set<string>>(new Set())
const { t } = useI18n()
const $q = useQuasar()

const reconstructedExecutionResult = computed<ExecutionResult | null>(() => {
    if (props.executionResult || !props.llmCalls?.length) return null
    const calls = [...props.llmCalls].sort((left, right) => (
        left.started_at.localeCompare(right.started_at)
    ))
    const results = calls.map(call => callExecutionResult(
        call,
        t('task.llmCalls.toolPending'),
        {
            contextTitle: t('llmCalls.context.title'),
            contextKey: t('llmCalls.context.key'),
            contextValue: t('llmCalls.context.value'),
            agentName: props.agentName,
            userName: props.userName,
        },
    ))
    const lastResult = results[results.length - 1]
    const lastCall = calls[calls.length - 1]
    if (!lastResult || !lastCall) return null
    const result = [...results].reverse().find(item => item.result.trim())?.result || ''
    return {
        prompt: lastResult.prompt,
        system_prompt: lastResult.system_prompt,
        messages: results.flatMap(item => item.messages || []),
        execution_time: results.reduce((total, item) => total + item.execution_time, 0),
        result,
        cost: results.reduce((total, item) => total + item.cost, 0),
        tools_used: [...new Set(results.flatMap(item => item.tools_used))],
        metadata: {
            agent_run_id: lastCall.agent_run_id,
            reconstructed_from_llm_calls: true,
        },
        success: calls.every(call => call.status === 'completed'),
    }
})

const displayedExecutionResult = computed(
    () => props.executionResult || reconstructedExecutionResult.value
)
const executionSucceeded = computed(
    () => props.executionSuccess ?? displayedExecutionResult.value?.success ?? false,
)
const displayedMessages = computed<AIMessage[]>(() => displayedExecutionResult.value?.messages || [])

// ExecutionResult.prompt is the objective passed to the runtime, not the complete
// provider request. Conversation and voice monitoring already preload the persisted
// LLM calls, whose latest request contains the full message history actually sent.
const latestRequestExecutionResult = computed<ExecutionResult | null>(() => {
    const latestCall = [...(props.llmCalls || [])]
        .sort((left, right) => left.started_at.localeCompare(right.started_at))
        .at(-1)
    if (!latestCall) return null
    return callExecutionResult(
        latestCall,
        t('task.llmCalls.toolPending'),
        {
            contextTitle: t('llmCalls.context.title'),
            contextKey: t('llmCalls.context.key'),
            contextValue: t('llmCalls.context.value'),
            agentName: props.agentName,
            userName: props.userName,
        },
    )
})

const displayedPrompt = computed(
    () => latestRequestExecutionResult.value?.prompt || displayedExecutionResult.value?.prompt || ''
)
const displayedSystemPrompt = computed(
    () => latestRequestExecutionResult.value?.system_prompt
        || displayedExecutionResult.value?.system_prompt
        || ''
)

const memoryToolNames = new Set([
    'memory_search',
    'memory_get',
    'memory_remember',
    'memory_index',
    'memory_forget',
    'memory_summarize'
])

interface MemoryContextTrace {
    enabled: boolean
    query: string
    count: number
    retrievedCount: number
    truncated: boolean
    memoryIds: string[]
    error: string
}

const normalizedToolName = (name: string | undefined): string => {
    let value = name || ''
    const prefixes = ['mcp_galaris_', 'mcp__galaris__', 'galaris_']
    let changed = true
    while (changed) {
        changed = false
        for (const prefix of prefixes) {
            if (value.startsWith(prefix)) {
                value = value.slice(prefix.length)
                changed = true
                break
            }
        }
    }
    return value
}

const memoryCalls = computed(() => displayedMessages.value
    .map((message, index) => ({ message, index, operation: normalizedToolName(message.tool_name) }))
    .filter(({ message, operation }) => message.type === 'tool' && memoryToolNames.has(operation)))

const memoryContext = computed<MemoryContextTrace | null>(() => {
    const raw = displayedExecutionResult.value?.metadata?.memory_context
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
    const data = raw as Record<string, unknown>
    const memoryIds = Array.isArray(data.memory_ids)
        ? data.memory_ids.map(value => String(value))
        : []
    const rawCount = data.count
    const count = typeof rawCount === 'number' && Number.isFinite(rawCount)
        ? Math.max(0, Math.trunc(rawCount))
        : memoryIds.length
    const rawRetrievedCount = data.retrieved_count
    const retrievedCount = typeof rawRetrievedCount === 'number' && Number.isFinite(rawRetrievedCount)
        ? Math.max(count, Math.trunc(rawRetrievedCount))
        : count
    return {
        enabled: data.enabled === true,
        query: typeof data.query === 'string' ? data.query : '',
        count,
        retrievedCount,
        truncated: data.truncated === true,
        memoryIds,
        error: typeof data.error === 'string' ? data.error : ''
    }
})

const memoryOperationCount = computed(
    () => memoryCalls.value.length + (memoryContext.value ? 1 : 0)
)
const showMemoryTab = computed(
    () => Boolean(props.showMemory)
)
const hasLlmCallSource = computed(
    () => Boolean(props.taskId) || props.llmCalls !== undefined
)
const runtimeRunId = computed(() => {
    const value = displayedExecutionResult.value?.metadata?.runtime_run_id
    return typeof value === 'string' ? value : ''
})
const memoryAgentId = computed<number | null>(() => {
    if (typeof props.agentId === 'number') return props.agentId
    const value = displayedExecutionResult.value?.metadata?.agent_id
    return typeof value === 'number' && Number.isInteger(value) ? value : null
})

const copyRuntimeRunId = async (): Promise<void> => {
    if (!runtimeRunId.value) return
    try {
        await copyToClipboard(runtimeRunId.value)
        $q.notify({
            message: t('task.notify.idCopied'),
            color: 'positive',
            icon: 'content_copy',
            timeout: 1500,
            position: 'top'
        })
    } catch (err) {
        console.error('Failed to copy runtime run ID:', err)
        $q.notify({
            message: t('task.notify.copyError'),
            color: 'negative',
            icon: 'error',
            timeout: 3000,
            position: 'top'
        })
    }
}

function stepKey(step: AIMessage, index: number): string {
    return step.stream_id || `legacy:${index}`
}

// Expansion belongs to the message, not its position in a refreshed snapshot.
watch(
    () => {
        const index = displayedMessages.value.length - 1
        const last = displayedMessages.value[index]
        return last ? stepKey(last, index) : null
    },
    (key, previousKey) => {
        if (key) {
            expandedSteps.value.add(key)
            if (!previousKey) activeTab.value = 'trace'
        }
    },
    { immediate: true }
)

const toggleStep = (key: string): void => {
    if (expandedSteps.value.has(key)) {
        expandedSteps.value.delete(key)
    } else {
        expandedSteps.value.add(key)
    }
}

const truncateContent = (content: string | null): string => {
    if (!content) return ''
    const stripped = content.replace(/<[^>]*>/g, '').replace(/\n/g, ' ').trim()
    return stripped.length > 50 ? stripped.substring(0, 50) + '...' : stripped
}

// Executors emit model reasoning as a synthetic `thinking` tool. Classify it
// separately so the timeline can distinguish it visually.
const stepKind = (step: AIMessage): string => {
    if (step.type === 'tool' && step.tool_name === 'thinking') return 'thinking'
    return step.type
}

const getStepColor = (step: AIMessage): string => {
    switch (stepKind(step)) {
        case 'text': return 'primary'
        case 'image': return 'purple'
        case 'audio': return 'orange'
        case 'video': return 'deep-purple'
        case 'tool': return 'teal'
        case 'thinking': return 'amber-9'
        default: return 'grey'
    }
}

const getStepIcon = (step: AIMessage): string => {
    switch (stepKind(step)) {
        case 'text': return 'article'
        case 'image': return 'image'
        case 'audio': return 'audiotrack'
        case 'video': return 'videocam'
        case 'tool': return 'build'
        case 'thinking': return 'psychology'
        default: return 'help'
    }
}

const formatArgumentsToTable = (args: Record<string, unknown>): Array<{ name: string; value: string }> => {
    return Object.entries(args).map(([name, value]) => ({
        name,
        value: typeof value === 'object' ? JSON.stringify(value) : String(value)
    }))
}

// Table columns for arguments display
const argumentColumns = computed(() => [
    { name: 'name', label: t('task.execution.argument'), field: 'name', align: 'left' as const },
    { name: 'value', label: t('task.execution.value'), field: 'value', align: 'left' as const }
])

const formatExecutionTime = (time: number): string => {
    if (time == null || isNaN(time)) {
        return '—'
    }
    if (time < 1) {
        return `${Math.round(time * 1000)}ms`
    } else if (time < 60) {
        return `${time.toFixed(2)}s`
    } else {
        const minutes = Math.floor(time / 60)
        const seconds = (time % 60).toFixed(2)
        return `${minutes}m ${seconds}s`
    }
}

const formatCostShort = (cost: number): string => {
    if (cost == null || isNaN(cost)) return '$0.00'
    if (cost === 0) return '$0.00'

    // Convert to a string to inspect the decimal part.
    const costStr = cost.toString()

    // Use two decimal places for integers and short decimal values.
    const decimalPart = costStr.split('.')[1]
    if (!decimalPart || decimalPart.length <= 2) {
        return `$${cost.toFixed(2)}`
    }

    // Count leading zeros after the decimal point.
    const leadingZeros = decimalPart.match(/^0*/)?.[0].length || 0

    // Cap very small values at six decimal places.
    if (leadingZeros >= 5) {
        return `$${cost.toFixed(6)}`
    }

    // Otherwise preserve significant decimals, up to six places.
    const significantDigits = decimalPart.substring(leadingZeros)
    const totalDecimals = Math.min(leadingZeros + significantDigits.length, 6)

    return `$${cost.toFixed(totalDecimals)}`
}

</script>

<style scoped>
.result-pre {
    white-space: pre-wrap;
    word-break: break-word;
    font-family: 'Courier New', monospace;
    font-size: 0.85em;
    margin: 0;
}

.info-item {
    margin-bottom: 16px;
}

.info-label {
    font-size: 0.75rem;
    color: #666;
    text-transform: uppercase;
    font-weight: 500;
    margin-bottom: 4px;
}

.exec-expansion :deep(.q-expansion-item__container) {
    border-radius: 8px;
}

.exec-expansion :deep(.q-expansion-item__header) {
    border-radius: 8px;
}

:deep(.execution-result-header--hidden) {
    display: none;
}

.q-tab-panels {
    background: transparent;
}

.trace-container {
    max-height: 500px;
    overflow-y: auto;
}

.trace-step {
    margin-bottom: 16px;
}

.trace-step-header {
    display: flex;
    align-items: center;
    margin-bottom: 8px;
}

.trace-card {
    border-left: 3px solid #ccc;
}

.trace-card.tool-card {
    border-left-color: #00bcd4;
}

.trace-card.tool-card.thinking-card {
    border-left-color: #ff8f00;
}

.arguments-table {
    font-size: 0.85em;
    margin: 0;
    border-bottom: 1px solid #e0e0e0;
}

.runtime-run-badge {
    max-width: 100%;
    overflow-wrap: anywhere;
    opacity: 0.8;
    letter-spacing: normal;
    transition: opacity 0.15s ease;
}

.runtime-run-badge:hover,
.runtime-run-badge:focus-visible {
    opacity: 1;
}

/* Use fixed-width wrapping cells without a horizontal scrollbar. */
.arguments-table :deep(.q-table) {
    table-layout: fixed;
    width: 100%;
}

.arguments-table :deep(.q-table__middle) {
    overflow-x: hidden;
}

.arguments-table :deep(td:first-child),
.arguments-table :deep(th:first-child) {
    width: 30%;
}

.arguments-table :deep(.q-table__top) {
    display: none;
}

.arguments-table :deep(th) {
    font-weight: 600;
    background: #f5f5f5;
    padding: 4px 8px;
}

.arguments-table :deep(td) {
    padding: 4px 8px;
    vertical-align: top;
}

.arguments-table :deep(.q-table tbody tr:last-child td) {
    border-bottom: none;
}

.argument-name,
.argument-value {
    display: inline-block;
    max-width: 100%;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
}

.argument-name {
    color: #00897b;
    font-weight: 500;
}

.argument-value {
    color: #333;
}

body.body--dark .info-label {
    color: #9e9e9e;
}

body.body--dark .argument-name {
    color: #4db6ac;
}

body.body--dark .argument-value {
    color: #d0d0d0;
}

/* Timeline styles */
.trace-timeline {
    display: flex;
    flex-direction: column;
}

.timeline-item {
    display: flex;
    flex-direction: row;
    min-height: 32px;
}

.timeline-connector {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 20px;
    flex-shrink: 0;
}

.timeline-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: #ccc;
    flex-shrink: 0;
    margin-top: 8px;
}

.timeline-dot-text { background: #1976d2; }
.timeline-dot-image { background: #9c27b0; }
.timeline-dot-audio { background: #ff9800; }
.timeline-dot-video { background: #673ab7; }
.timeline-dot-tool { background: #009688; }
.timeline-dot-thinking { background: #ff8f00; }
.timeline-dot-pending { background: #9e9e9e; }

.timeline-line {
    width: 2px;
    flex: 1;
    min-height: 20px;
    background: #e0e0e0;
}

body.body--dark .timeline-line {
    background: #3a3f47;
}

.timeline-content-col {
    flex: 1;
    display: flex;
    flex-direction: column;
}

.timeline-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex: 1;
    padding: 4px 8px;
    background: #f5f5f5;
    border-radius: 4px;
    cursor: pointer;
    margin: 4px 0;
}

.timeline-header:hover {
    background: #eeeeee;
}

.timeline-header--pending,
.timeline-header--pending:hover {
    cursor: default;
    background: #f5f5f5;
}

body.body--dark .arguments-table :deep(th) {
    background: #2a2a2a;
}

body.body--dark .timeline-header {
    background: #2a2a2a;
}

body.body--dark .timeline-header:hover {
    background: #333333;
}

body.body--dark .timeline-header--pending,
body.body--dark .timeline-header--pending:hover {
    background: #2a2a2a;
}

.timeline-header-left {
    display: flex;
    align-items: center;
}

.timeline-header-right {
    display: flex;
    align-items: center;
}

@media (max-width: 1023px) {
    .timeline-content-col {
        min-width: 0;
    }

    .timeline-header {
        flex-wrap: wrap;
        gap: 4px 8px;
    }

    .timeline-header-left,
    .timeline-header-right {
        max-width: 100%;
        min-width: 0;
    }

    .timeline-header-left .q-icon {
        flex-shrink: 0;
    }

    .tool-name {
        overflow-wrap: anywhere;
        min-width: 0;
    }

    .timeline-header-right {
        flex-wrap: wrap;
        justify-content: flex-end;
        row-gap: 4px;
        margin-left: auto;
    }
}

.timeline-expanded {
    padding: 4px 0;
}

.tool-card .q-card__section {
    max-height: 300px;
    overflow-y: auto;
    overflow-x: hidden;
}

/* Wrap response Markdown inside function-call blocks instead of showing a
   horizontal scrollbar. */
.tool-card :deep(.markdown-content pre) {
    overflow-x: visible;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
}

.tool-card :deep(.markdown-content pre code),
.tool-card :deep(.markdown-content code) {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
}

.trace-card {
    border-left: 3px solid #ccc;
}

.trace-card.tool-card {
    border-left-color: #00bcd4;
}
</style>
