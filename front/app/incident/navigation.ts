import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  monitor: {
    children: {
      incidents: {
        label: 'incidents.title',
        description: 'incidents.description',
        icon: 'bug_report',
        order: 40,
        to: '/incident',
        privileges: [privileges.INCIDENT_ACCESS, privileges.INCIDENT_EDIT],
      },
    },
  },
}

export default navigation
