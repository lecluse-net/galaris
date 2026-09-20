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
        privileges: [privileges.TASK_ACCESS],
      }
    }
  }
}

export default navigation
