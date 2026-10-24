import type { NavigationTree } from '@/core/navigation'
import { privileges, usePrivilegeStore } from '@/core/authorize'

const navigation: NavigationTree = {
  monitor: {
    children: {
      dream: {
        label: 'nav.dream',
        description: 'nav.dream_desc',
        icon: 'bedtime',
        order: 20,
        to: '/dream',
        privileges: [privileges.DREAM_ACCESS],
        visible: () => usePrivilegeStore().hasPrivilege(privileges.AGENT_MANAGE_ALL),
      },
    },
  },
}

export default navigation
