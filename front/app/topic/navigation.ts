import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  knowledge: {
    children: {
      topics: {
        label: 'nav.topics',
        description: 'nav.topics_desc',
        icon: 'folder_copy',
        order: 30,
        to: '/topic',
        privileges: [privileges.TOPIC_ACCESS, privileges.TOPIC_EDIT],
      },
    },
  },
}

export default navigation
