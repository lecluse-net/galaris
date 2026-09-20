import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  configure: {
    children: {
      llm: {
        label: 'nav.llm',
        icon: 'smart_toy',
        order: 10,
        to: '/llm',
        description: 'nav.llm_desc',
        privileges: [privileges.LLM_PROVIDER_ACCESS],
      }
    }
  }
}

export default navigation
