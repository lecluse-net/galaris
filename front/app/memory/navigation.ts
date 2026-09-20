import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  knowledge: {
    children: {
      documents: {
        label: 'nav.documents',
        description: 'nav.documents_desc',
        icon: 'description',
        order: 10,
        to: '/memory/documents',
        privileges: [privileges.MEMORY_ACCESS],
      },
      memory: {
        label: 'nav.memory',
        description: 'nav.memory_desc',
        icon: 'memory',
        order: 20,
        to: '/memory',
        privileges: [privileges.MEMORY_ACCESS],
      },
      contacts: {
        label: 'nav.contacts',
        description: 'nav.contacts_desc',
        icon: 'contacts',
        order: 25,
        to: '/memory/contacts',
        privileges: [privileges.MEMORY_ACCESS],
      },
    },
  },
}

export default navigation
