import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  monitor: {
    children: {
      dream: {
        label: 'nav.dream',
        description: 'nav.dream_desc',
        icon: 'bedtime',
        order: 20,
        to: '/dream',
        privileges: [privileges.TASK_ACCESS, privileges.AGENT_MANAGE_ALL],
      },
    },
  },
}

export default navigation
