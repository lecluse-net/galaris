import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  admin: {
    children: {
      plugins: {
        label: 'plugins.title',
        description: 'plugins.description',
        icon: 'extension',
        order: 60,
        to: '/plugin',
        privileges: [privileges.PLUGIN_ACCESS, privileges.PLUGIN_EDIT],
      },
    },
  },
}

export default navigation
