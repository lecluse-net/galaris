<template>
    <q-expansion-item v-if="plan || planning" icon="account_tree" :label="$t('task.planner.title')"
        header-class="text-teal text-subtitle2" class="planner-expansion q-mt-md" dense toggle-indicator expanded>
        <template v-slot:header>
            <q-item-section avatar>
                <q-icon name="account_tree" color="teal" />
            </q-item-section>
            <q-item-section>
                <q-item-label>{{ $t('task.planner.title') }}</q-item-label>
                <q-item-label v-if="planning && !plan" caption class="text-teal">
                    {{ $t('task.planner.starting') }}
                </q-item-label>
            </q-item-section>
            <q-item-section side v-if="plan">
                <div class="row q-gutter-xs">
                    <StatusBadge
                        v-if="statusSuccess !== null"
                        :tone="statusSuccess ? 'success' : 'error'"
                        :icon="statusSuccess ? 'check_circle' : 'error'"
                        :label="statusSuccess ? $t('task.dispatch.success') : $t('task.dispatch.failure')"
                    />
                    <q-badge color="teal" size="sm">
                        <q-icon name="format_list_numbered" size="xs" class="q-mr-xs" />
                        {{ rootSteps.length }}
                    </q-badge>
                    <q-badge color="blue" size="sm">
                        <q-icon name="trending_up" size="xs" class="q-mr-xs" />
                        {{ completedRootSteps }}/{{ rootSteps.length }}
                    </q-badge>
                    <q-badge v-if="hasExecutionTime" color="blue" size="sm">
                        <q-icon name="timer" size="xs" class="q-mr-xs" />
                        {{ formatExecutionTime(plan.execution_time || 0) }}
                    </q-badge>
                    <q-badge v-if="hasCost" color="purple" size="sm">
                        <q-icon name="attach_money" size="xs" class="q-mr-xs" />
                        {{ formatCostShort(plan.cost || 0) }}
                    </q-badge>
                </div>
            </q-item-section>
            <q-item-section side v-else-if="planning">
                <q-spinner-dots color="teal" size="24px" />
            </q-item-section>
        </template>

        <q-card v-if="!plan" flat bordered class="q-mt-sm">
            <q-card-section class="text-center text-grey q-pa-md">
                <q-spinner color="teal" size="2em" class="q-mb-sm" />
                <div>{{ $t('task.planner.starting') }}</div>
            </q-card-section>
        </q-card>

        <q-card v-else flat bordered class="q-mt-sm">
            <q-card-section>
                <q-tabs v-model="activeTab" dense class="text-grey" active-color="primary" indicator-color="primary"
                    align="left" narrow-indicator>
                    <q-tab name="data">
                        <div class="row items-center no-wrap">
                            <q-icon name="analytics" class="q-mr-xs" />
                            <span>{{ $t('task.planner.summary') }}</span>
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
                </q-tabs>

                <q-separator />

                <q-tab-panels v-model="activeTab" animated>
                    <q-tab-panel name="data">
                        <q-banner v-if="clarificationQuestions.length" rounded class="bg-orange-1 text-orange-10 q-mb-md">
                            <template v-slot:avatar>
                                <q-icon name="help" color="orange-9" />
                            </template>
                            <div class="text-subtitle2 q-mb-xs">{{ $t('task.planner.clarifications') }}</div>
                            <ul class="planner-list">
                                <li v-for="question in clarificationQuestions" :key="question">{{ question }}</li>
                            </ul>
                        </q-banner>

                        <div class="row q-col-gutter-md q-mb-md">
                            <div class="col-12 col-sm-4">
                                <div class="info-item">
                                    <div class="info-label">{{ $t('task.planner.rootSteps') }}</div>
                                    <div class="text-body2 text-weight-bold">{{ rootSteps.length }}</div>
                                </div>
                            </div>
                            <div class="col-12 col-sm-4">
                                <div class="info-item">
                                    <div class="info-label">{{ $t('task.planner.totalSteps') }}</div>
                                    <div class="text-body2 text-weight-bold">{{ flattenedSteps.length }}</div>
                                </div>
                            </div>
                            <div class="col-12 col-sm-4">
                                <div class="info-item">
                                    <div class="info-label">{{ $t('task.planner.progress') }}</div>
                                    <div class="row items-center no-wrap q-gutter-sm">
                                        <q-linear-progress :value="progressValue" color="teal" rounded class="col" />
                                        <span class="text-caption text-grey">{{ completedRootSteps }}/{{ rootSteps.length }}</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div v-if="brief" class="q-mb-lg">
                            <div class="text-h6 q-mb-md flex items-center">
                                <q-icon name="assignment" class="q-mr-sm" />
                                {{ $t('task.planner.brief') }}
                            </div>
                            <div class="planner-brief">
                                <div v-for="field in briefFields" :key="field.key" class="planner-brief-section">
                                    <h2 class="planner-brief-heading">{{ field.label }}</h2>
                                    <Markdown class="text-body2" :content="field.value" />
                                </div>
                                <div v-for="field in listFields" :key="field.key" class="planner-brief-section">
                                    <h2 class="planner-brief-heading">{{ field.label }}</h2>
                                    <ul class="planner-list">
                                        <li v-for="item in field.items" :key="item">{{ item }}</li>
                                    </ul>
                                </div>
                            </div>
                        </div>

                        <div v-if="flattenedSteps.length">
                            <div class="text-h6 q-mb-md flex items-center">
                                <q-icon name="schema" class="q-mr-sm" />
                                {{ $t('task.planner.steps') }}
                            </div>
                            <q-list bordered separator dense class="rounded-borders planner-steps">
                                <q-item v-for="step in flattenedSteps" :key="step.key" :class="{ 'current-step': step.isCurrentRoot }">
                                    <q-item-section avatar>
                                        <q-badge color="teal" text-color="white">{{ step.number }}</q-badge>
                                    </q-item-section>
                                    <q-item-section :style="{ paddingLeft: `${step.depth * 16}px` }">
                                        <q-item-label class="row items-center q-gutter-xs">
                                            <span>{{ step.label }}</span>
                                            <q-badge v-if="step.effort" :color="getEffortColor(step.effort)" size="sm">
                                                {{ $t(`task.dispatch.effortLevels.${step.effort}`) }}
                                            </q-badge>
                                            <q-badge v-if="step.childCount" color="grey-4" text-color="grey-8" size="sm">
                                                {{ $t('task.planner.substeps', { count: step.childCount }) }}
                                            </q-badge>
                                        </q-item-label>
                                        <q-item-label v-if="step.objective" caption lines="3">{{ richTextExcerpt(step.objective) }}</q-item-label>
                                        <q-item-label v-if="step.announce" caption lines="2" class="text-teal">
                                            {{ step.announce }}
                                        </q-item-label>
                                    </q-item-section>
                                </q-item>
                            </q-list>
                        </div>
                        <div v-else class="text-grey text-center q-pa-md">
                            {{ $t('task.planner.noPlan') }}
                        </div>
                    </q-tab-panel>

                    <q-tab-panel name="prompt">
                        <div v-if="plan.prompt" class="text-body2 q-pa-sm rounded-borders">
                            <Markdown :content="plan.prompt" />
                        </div>
                        <div v-else class="text-grey text-center q-pa-md">
                            {{ $t('task.planner.noPrompt') }}
                        </div>
                    </q-tab-panel>

                    <q-tab-panel name="system-prompt">
                        <div v-if="plan.system_prompt" class="text-body2 q-pa-sm rounded-borders">
                            <Markdown :content="plan.system_prompt" />
                        </div>
                        <div v-else class="text-grey text-center q-pa-md">
                            {{ $t('task.planner.noSystemPrompt') }}
                        </div>
                    </q-tab-panel>
                </q-tab-panels>
            </q-card-section>
        </q-card>
    </q-expansion-item>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Effort, PlanStep, TaskPlan, TaskStatus } from '../types'
import Markdown from '@/core/util/components/Markdown.vue'
import { StatusBadge, richTextExcerpt } from '@/core/util'

const props = defineProps<{
    plan: TaskPlan | null
    status?: TaskStatus
    planning?: boolean
}>()

const activeTab = ref('data')
const { t } = useI18n()

interface FlatStep {
    key: string
    path: number[]
    number: string
    depth: number
    label: string
    objective: string
    announce: string
    effort?: Effort
    childCount: number
    isCurrentRoot: boolean
}

const rootSteps = computed<PlanStep[]>(() => Array.isArray(props.plan?.steps) ? props.plan.steps : [])
const brief = computed(() => props.plan?.brief || null)
const clarificationQuestions = computed<string[]>(() =>
    Array.isArray(props.plan?.clarification_questions) ? props.plan.clarification_questions : []
)
const cursor = computed(() => Number(props.plan?.cursor ?? 0))
const completedRootSteps = computed(() => {
    if (props.status === 'SUCCESS') return rootSteps.value.length
    return Math.min(Math.max(cursor.value, 0), rootSteps.value.length)
})
const progressValue = computed(() => {
    if (!rootSteps.value.length) return 0
    return completedRootSteps.value / rootSteps.value.length
})
const statusSuccess = computed<boolean | null>(() => {
    if (typeof props.plan?.success === 'boolean') return props.plan.success
    if (props.status === 'SUCCESS') return true
    if (props.status === 'ERROR') return false
    return null
})
const hasExecutionTime = computed(() => typeof props.plan?.execution_time === 'number')
const hasCost = computed(() => typeof props.plan?.cost === 'number')

const briefFields = computed(() => {
    const value = brief.value
    if (!value) return []
    return [
        { key: 'objective', label: t('task.planner.objective'), value: value.objective },
        { key: 'context', label: t('task.planner.context'), value: value.context },
        { key: 'strategy', label: t('task.planner.strategy'), value: value.strategy },
        { key: 'rationale', label: t('task.planner.rationale'), value: value.rationale },
    ].filter((field): field is { key: string; label: string; value: string } => Boolean(field.value?.trim()))
})

const listFields = computed(() => {
    const value = brief.value
    if (!value) return []
    return [
        { key: 'constraints', label: t('task.planner.constraints'), items: value.constraints },
        { key: 'success_criteria', label: t('task.planner.successCriteria'), items: value.success_criteria },
        { key: 'deliverables', label: t('task.planner.deliverables'), items: value.deliverables },
    ].map(field => ({
        ...field,
        items: (field.items || []).map(item => String(item).trim()).filter(Boolean)
    })).filter(field => field.items.length)
})

const flattenedSteps = computed<FlatStep[]>(() => {
    const rows: FlatStep[] = []
    const visit = (steps: PlanStep[], depth: number, prefix: number[]) => {
        steps.forEach((step, index) => {
            const path = [...prefix, index]
            const number = path.map(item => item + 1).join('.')
            const children = Array.isArray(step.steps) ? step.steps : []
            rows.push({
                key: path.join('.'),
                path,
                number,
                depth,
                label: step.label?.trim() || step.objective?.trim() || t('task.detail.planStep', { n: number }),
                objective: step.objective?.trim() || '',
                announce: step.announce?.trim() || '',
                effort: step.effort,
                childCount: children.length,
                isCurrentRoot: depth === 0 && index === cursor.value && props.status !== 'SUCCESS',
            })
            if (children.length) visit(children, depth + 1, path)
        })
    }
    visit(rootSteps.value, 0, [])
    return rows
})

const getEffortColor = (effort: string): string => {
    switch (effort) {
        case 'high': return 'deep-orange'
        case 'standard': return 'blue-grey'
        default: return 'grey'
    }
}

const formatExecutionTime = (time: number): string => {
    if (time == null || isNaN(time)) return '—'
    if (time < 1) return `${Math.round(time * 1000)}ms`
    if (time < 60) return `${time.toFixed(2)}s`
    const minutes = Math.floor(time / 60)
    const seconds = (time % 60).toFixed(2)
    return `${minutes}m ${seconds}s`
}

const formatCostShort = (cost: number): string => {
    if (cost == null || isNaN(cost)) return '$0.00'
    if (cost === 0) return '$0.00'

    const costStr = cost.toString()
    const decimalPart = costStr.split('.')[1]
    if (!decimalPart || decimalPart.length <= 2) return `$${cost.toFixed(2)}`

    const leadingZeros = decimalPart.match(/^0*/)?.[0].length || 0
    if (leadingZeros >= 5) return `$${cost.toFixed(6)}`

    const significantDigits = decimalPart.substring(leadingZeros)
    const totalDecimals = Math.min(leadingZeros + significantDigits.length, 6)

    return `$${cost.toFixed(totalDecimals)}`
}
</script>

<style scoped>
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

body.body--dark .info-label {
    color: #9e9e9e;
}

.planner-expansion :deep(.q-expansion-item__container) {
    border-radius: 8px;
}

.planner-expansion :deep(.q-expansion-item__header) {
    border-radius: 8px;
}

.q-tab-panels {
    background: transparent;
}

.planner-list {
    margin: 0;
    padding-left: 20px;
}

.planner-brief {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.planner-brief-heading {
    margin: 0 0 6px;
    font-size: 1.25rem;
    font-weight: 600;
    line-height: 1.3;
}

.planner-brief-section :deep(.markdown-content > :first-child) {
    margin-top: 0;
}

.planner-brief-section :deep(.markdown-content > :last-child) {
    margin-bottom: 0;
}

.planner-steps .current-step {
    background: rgba(0, 150, 136, 0.08);
}

.planner-steps :deep(.q-item__section--main) {
    min-width: 0;
}
</style>
