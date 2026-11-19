import type { BridgeSettingsContribution } from '@/core/params'
import { defineAsyncView } from '@/core/util/facade'

const HarnessPreferences = defineAsyncView(() => import('./components/HarnessPreferences.vue'))
const TaskExecutionSettings = defineAsyncView(() => import('./components/TaskExecutionSettings.vue'))

export default {
  area: 'harness',
  placement: 'overview',
  kind: 'catalog',
  label: 'Harnesses',
  icon: 'smart_toy',
  guideKey: 'harnesses.catalog.hint',
  stepsKey: 'harnesses.catalog.steps',
  docsUrl: '/params/harnesses',
  fields: [],
  component: HarnessPreferences,
  taskExecutionComponent: TaskExecutionSettings,
} satisfies BridgeSettingsContribution
