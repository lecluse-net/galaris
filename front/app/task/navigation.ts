import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  monitor: {
    children: {
      tasks: {
        label: 'nav.task',
        description: 'nav.task_desc',
        icon: 'monitor_heart',
        order: 10,
        to: '/task',
        privileges: [privileges.TASK_ACCESS, privileges.TASK_EDIT, privileges.CONVERSATION_ACCESS, privileges.CONVERSATION_CONTROL, privileges.VOICE_HISTORY_ACCESS, privileges.VOICE_HISTORY_CONTROL, privileges.LLM_CALL_ACCESS, privileges.LLM_CALL_CONTROL, privileges.PROCESS_READ, privileges.PROCESS_ADMIN],
      }
    }
  }
}

export default navigation
