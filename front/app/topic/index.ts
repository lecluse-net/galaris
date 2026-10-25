import { defineAsyncView } from '@/core/util'

export { default as TopicBadge } from './components/TopicBadge.vue'
export { default as TopicFormDialog } from './components/TopicFormDialog.vue'
export { default as TopicSelect } from './components/TopicSelect.vue'
export { useTopicRefs } from './composables/useTopicRefs'
export type {
  Topic,
  TopicAssignmentAudit,
  TopicAssignmentChangeScope,
  TopicAssignmentSubjectKind,
} from './types'
export const TopicDetail = defineAsyncView(() => import('./components/TopicDetail.vue'))
