import type { BridgeSettingsContribution } from '@/core/params'
import HarnessPreferences from './components/HarnessPreferences.vue'
import TaskExecutionSettings from './components/TaskExecutionSettings.vue'

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
