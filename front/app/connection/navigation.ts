import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
import { isMailNavigationVisible } from './availability'

const navigation: NavigationTree = {
  monitor: {
    children: {
      permissions: {
        label: 'permissions.title', description: 'permissions.description', icon: 'verified_user',
        order: 31, to: '/connection/permissions',
        privileges: [privileges.CONNECTION_ACCESS, privileges.CONNECTION_EDIT],
      },
      mailJournal: {
        label: 'nav.mailJournal',
        icon: 'outbox',
        order: 30,
        to: '/connection/mail',
        description: 'nav.mailJournal_desc',
        privileges: [privileges.CONNECTION_ACCESS],
        visible: isMailNavigationVisible,
      },
    },
  },
}

export default navigation
