import { privileges } from '@/core/authorize'
import type { LabSectionKey } from './presentation'

export type LabPrivilegePair = readonly [read: string, edit: string]

export const labSectionPrivileges = {
  tasks: [privileges.EVALUATION_ACCESS, privileges.EVALUATION_EDIT],
  dispatcher: [
    privileges.DISPATCHER_EVALUATION_ACCESS,
    privileges.DISPATCHER_EVALUATION_EDIT,
  ],
  briefing: [privileges.BRIEFING_EVALUATION_ACCESS, privileges.BRIEFING_EVALUATION_EDIT],
  planner: [privileges.PLANNER_EVALUATION_ACCESS, privileges.PLANNER_EVALUATION_EDIT],
  topic_classification: [
    privileges.TOPIC_CLASSIFICATION_EVALUATION_ACCESS,
    privileges.TOPIC_CLASSIFICATION_EVALUATION_EDIT,
  ],
  memory_extraction: [
    privileges.MEMORY_EXTRACTION_EVALUATION_ACCESS,
    privileges.MEMORY_EXTRACTION_EVALUATION_EDIT,
  ],
  outcome_reflection: [
    privileges.OUTCOME_REFLECTION_EVALUATION_ACCESS,
    privileges.OUTCOME_REFLECTION_EVALUATION_EDIT,
  ],
  goal_tracking: [
    privileges.GOAL_TRACKING_EVALUATION_ACCESS,
    privileges.GOAL_TRACKING_EVALUATION_EDIT,
  ],
  task_executor: [
    privileges.TASK_EXECUTOR_EVALUATION_ACCESS,
    privileges.TASK_EXECUTOR_EVALUATION_EDIT,
  ],
  conversation_executor: [
    privileges.CONVERSATION_EXECUTOR_EVALUATION_ACCESS,
    privileges.CONVERSATION_EXECUTOR_EVALUATION_EDIT,
  ],
  voice_executor: [
    privileges.VOICE_EXECUTOR_EVALUATION_ACCESS,
    privileges.VOICE_EXECUTOR_EVALUATION_EDIT,
  ],
} satisfies Record<LabSectionKey, LabPrivilegePair>

export const allLabPrivileges = Object.values(labSectionPrivileges).flat()

export function hasAnyPrivilege(
  hasPrivilege: (privilege: string) => boolean,
  required: readonly string[],
): boolean {
  return required.some(hasPrivilege)
}
