import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  act: {
    children: {
      processes: {
        label: 'nav.processes',
        description: 'nav.processes_desc',
        icon: 'account_tree',
        to: '/process',
        order: 30,
        privileges: [privileges.PROCESS_READ],
      },
    },
  },
}

export default navigation
