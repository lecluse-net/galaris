import { defineAsyncView } from '@/core/util'

export const ExecutionResultComponent = defineAsyncView(() => import('./components/ExecutionResult.vue'))
export const TaskDetail = defineAsyncView(() => import('./components/TaskDetail.vue'))
export { default as TaskActivitySummary } from './components/TaskActivitySummary.vue'
export { default as TaskStartupTimingPanel } from './components/TaskStartupTiming.vue'
export type { TaskStartupTiming } from './activity'
export { useTaskActivity } from './useTaskActivity'
export { taskService } from './services/taskService'
export { useTaskStore } from './stores/taskStore'
export { taskResourceUri } from './resourceUri'
export {
  appendAIMessage,
  currentAIResponse,
  emptyAIResult,
  finalizeAIResult,
  reconcileAIResult,
  resetAIResultText,
} from './facade'
export {
  getTaskStatusBadgeColor,
  getTaskStatusBadgeTextColor,
  getTaskStatusTone,
  getTaskOperationalColor,
  getTaskOperationalIcon,
  getTaskStatusColor,
  getTaskStatusIcon,
  isTaskStatusAction,
  isUserPaused,
  pauseBadge,
  shouldAnimateTaskStatus,
} from './services/taskStatusService'
export type { AIMessage, AIResult, ExecutionResult, Task, TaskFull, TaskStatus } from './types'
