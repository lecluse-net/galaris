import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
    configure: {
        children: {
            skills: {
                label: 'nav.skills',
                icon: 'psychology',
                to: '/skill',
                order: 40,
                description: 'nav.skills_desc',
                privileges: [privileges.SKILL_ACCESS],
            },
        },
    },
}

export default navigation
