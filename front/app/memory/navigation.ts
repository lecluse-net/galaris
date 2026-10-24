import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  knowledge: {
    children: {
      memory: {
        label: 'nav.memory',
        description: 'nav.memory_desc',
        icon: 'memory',
        order: 20,
        to: '/memory',
        privileges: [privileges.MEMORY_ACCESS, privileges.MEMORY_EDIT, privileges.MEMORY_ADMIN],
      },
      contacts: {
        label: 'nav.contacts',
        description: 'nav.contacts_desc',
        icon: 'contacts',
        order: 25,
        to: '/memory/contacts',
        privileges: [privileges.CONTACT_ACCESS, privileges.CONTACT_EDIT],
      },
    },
  },
}

export default navigation
