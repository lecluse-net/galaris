import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  admin: {
    children: {
      authorizations: {
        label: 'nav.authorizations',
        icon: 'security',
        order: 50,
        to: '/authorize',
        description: 'nav.authorizations_desc',
        privileges: [privileges.READ_ROLE, privileges.MANAGE_ROLE, privileges.READ_PRIVILEGE, privileges.MANAGE_PRIVILEGE, privileges.READ_ASSIGNMENT, privileges.MANAGE_ASSIGNMENT],
      }
    }
  }
}

export default navigation
