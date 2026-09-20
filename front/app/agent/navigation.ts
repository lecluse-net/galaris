import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
    configure: {
        children: {
            agent: {
                label: 'nav.agent',
                icon: 'people',
                to: '/agent',
                order: 20,
                description: 'nav.agent_desc',
                privileges: [privileges.AGENT_ACCESS],
            }
        }
    }
}

export default navigation
