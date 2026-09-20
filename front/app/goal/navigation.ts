import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  act: {
    children: {
      goals: {
        label: 'nav.goal',
        description: 'nav.goal_desc',
        icon: 'flag_circle',
        order: 20,
        to: '/goal',
        privileges: [privileges.GOAL_ACCESS],
      },
    },
  },
}

export default navigation
