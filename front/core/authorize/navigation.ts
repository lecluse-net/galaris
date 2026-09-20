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
        privileges: [privileges.READ_ROLE],
      }
    }
  }
}

export default navigation
