import { defineAsyncView } from '@/core/util/facade'

export { default as TopicBadge } from './components/TopicBadge.vue'
export { default as TopicFormDialog } from './components/TopicFormDialog.vue'
export { default as TopicSelect } from './components/TopicSelect.vue'
export { useTopicRefs } from './composables/useTopicRefs'
export { topicService } from './services/topicService'
export type {
  Topic,
  TopicAssignmentAudit,
  TopicAssignmentChangeScope,
  TopicAssignmentSubjectKind,
} from './types'
export const TopicDetail = /* @__PURE__ */ defineAsyncView(() => import('./components/TopicDetail.vue'))
export { default as TopicAssignmentEditor } from './components/TopicAssignmentEditor.vue'
