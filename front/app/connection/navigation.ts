import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
import { isMailNavigationVisible } from './availability'

const navigation: NavigationTree = {
  monitor: {
    children: {
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
