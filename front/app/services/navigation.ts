import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  configure: {
    children: {
      tools: {
        label: 'nav.services',
        icon: 'hub',
        order: 30,
        to: '/services',
        description: 'nav.services_desc',
        privileges: [privileges.SERVICE_ACCESS, privileges.SERVICE_EDIT, privileges.CONNECTION_ACCESS, privileges.CONNECTION_EDIT, privileges.PERMISSION_ACCESS, privileges.PERMISSION_DECIDE, privileges.PERMISSION_REVOKE],
      }
    }
  }
}

export default navigation
