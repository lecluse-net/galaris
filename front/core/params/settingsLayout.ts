import type { SettingField } from './settingsTypes'
import {
    dreamFields, memoryAutomationFields, taskBudgetFields, taskCollaborationFields,
    taskCreationFields, taskRetryFields, taskSchedulerFields,
} from './settingsCatalog'

// Presentation only: retain the field definitions and their saving contracts.
export const dreamActivityFields = dreamFields.filter(field => field.name === 'DREAM_ENABLED')
export const dreamTopicFields = dreamFields.filter(field => (
    field.name === 'DREAM_TOPIC_CREATION_MODE' || field.input === 'prompt'
))
export const dreamLearningFields = dreamFields.filter(field => field.name.startsWith('DREAM_SKILL_'))
    .map(field => ({ ...field, advanced: field.name !== 'DREAM_SKILL_LEARNING_MODE' }))
export const dreamRuntimeFields = dreamFields.filter(field => (
    !dreamActivityFields.some(item => item.name === field.name)
    && !dreamTopicFields.some(item => item.name === field.name)
    && !dreamLearningFields.some(item => item.name === field.name)
))

export const memoryMaintenanceGroups = [
    { key: 'duplicates', prefix: 'MEMORY_DUPLICATE_' },
    { key: 'contradictions', prefix: 'MEMORY_CONTRADICTION_' },
    { key: 'aging', prefix: 'MEMORY_AGING_' },
].map(group => ({
    key: group.key,
    fields: memoryAutomationFields.filter(field => field.name.startsWith(group.prefix)),
}))
export const memoryRuntimeFields = memoryAutomationFields.filter(field => (
    !memoryMaintenanceGroups.some(group => group.fields.some(item => item.name === field.name))
))

const essentialBudgetNames = new Set([
    'TASK_ROOT_MAX_TOKENS', 'TASK_ROOT_MAX_COST', 'TASK_ROOT_MAX_SECONDS',
])
export const taskGroups: { key: string; icon: string; fields: SettingField[]; advanced?: boolean }[] = [
    { key: 'scheduler', icon: 'play_circle', fields: taskSchedulerFields.map(field => ({
        ...field, advanced: field.advanced || field.name === 'TASK_SCHEDULER_LEASE_SECONDS',
    })) },
    { key: 'budgets', icon: 'speed', fields: taskBudgetFields.map(field => ({
        ...field, advanced: !essentialBudgetNames.has(field.name),
    })) },
    { key: 'creation', icon: 'edit_note', fields: taskCreationFields, advanced: true },
    { key: 'retries', icon: 'replay', fields: taskRetryFields, advanced: true },
    { key: 'collaboration', icon: 'groups', fields: taskCollaborationFields, advanced: true },
]
