import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  configure: {
    children: {
      tools: {
        label: 'nav.tools',
        icon: 'build',
        order: 30,
        to: '/tools',
        description: 'nav.tools_desc',
        privileges: [privileges.TOOL_ACCESS],
      }
    }
  }
}

export default navigation
