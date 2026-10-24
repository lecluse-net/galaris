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
        privileges: [privileges.LLM_PROVIDER_ACCESS, privileges.LLM_PROVIDER_EDIT, privileges.LLM_MODEL_ACCESS, privileges.LLM_MODEL_EDIT, privileges.LLM_PROFILE_ACCESS, privileges.LLM_PROFILE_EDIT],
      }
    }
  }
}

export default navigation
