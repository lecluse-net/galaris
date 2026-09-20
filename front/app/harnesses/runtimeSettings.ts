import type { SettingField } from '@/core/params'

export const plannerFields: SettingField[] = [
    {
        name: 'ai.planner-system-prompt',
        labelKey: 'taskSettings.fields.plannerSystemPrompt',
        descriptionKey: 'taskSettings.fields.plannerSystemPromptHint',
        input: 'prompt',
        advanced: false,
    },
    {
        name: 'TASK_PLAN_MAX_DEPTH',
        labelKey: 'taskSettings.fields.planDepth',
        descriptionKey: 'taskSettings.fields.planDepthHint',
        input: 'integer',
        min: 1,
        max: 10,
    },
    {
        name: 'TASK_PLAN_MAX_NODES',
        labelKey: 'taskSettings.fields.planNodes',
        descriptionKey: 'taskSettings.fields.planNodesHint',
        input: 'integer',
        min: 1,
        max: 500,
    },
    {
        name: 'TASK_PLAN_MAX_LEAVES',
        labelKey: 'taskSettings.fields.planLeaves',
        descriptionKey: 'taskSettings.fields.planLeavesHint',
        input: 'integer',
        min: 1,
        max: 250,
    },
]

export const briefingFields: SettingField[] = [{
  name: 'ai.briefing-system-prompt',
  labelKey: 'harnesses.preferences.briefingPrompt',
  descriptionKey: 'harnesses.preferences.briefingPromptHint',
  input: 'prompt',
}]

export const executionLimitFields: SettingField[] = [
  {
    name: 'TASK_AGENT_MAX_REQUESTS',
    labelKey: 'taskSettings.fields.maxRequests',
    descriptionKey: 'taskSettings.fields.maxRequestsHint',
    input: 'integer', min: 1, max: 500,
  },
  {
    name: 'TASK_AGENT_MAX_TOOL_CALLS',
    labelKey: 'taskSettings.fields.maxToolCalls',
    descriptionKey: 'taskSettings.fields.maxToolCallsHint',
    input: 'integer', min: 1, max: 5000,
  },
]

export const inputFields: SettingField[] = [{
  name: 'PYDANTIC_AI_BINARY_INPUT_MAX_BYTES',
  labelKey: 'harnesses.inputFiles.maxBytes',
  descriptionKey: 'harnesses.inputFiles.hint',
  input: 'integer', sizeUnit: 'bytes', min: 1024, max: 1_048_576_000,
}]
