import { defineAsyncView } from '@/core/util/facade'

export const ExecutionResultComponent = /* @__PURE__ */ defineAsyncView(() => import('./components/ExecutionResult.vue'))
export const TaskDetail = /* @__PURE__ */ defineAsyncView(() => import('./components/TaskDetail.vue'))
export const ActiveTasksPanel = /* @__PURE__ */ defineAsyncView(() => import('./components/ActiveTasksPanel.vue'))
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
  getTaskDisplayStatus,
  canRetryTask,
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
