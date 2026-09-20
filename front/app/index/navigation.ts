import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
    monitor: {
        children: {
            dashboard: {
                label: 'nav.dashboard',
                icon: 'dashboard',
                to: '/dashboard',
                order: 1,
                description: 'nav.dashboard_desc',
                privileges: [privileges.TASK_ACCESS, privileges.TASK_EDIT],
            },
        },
    },
    admin: {},
    pageFooter: {
        children: {
            legal: {
                label: 'nav.legal',
                icon: 'gavel',
                to: '/legal',
                order: 1,
            },
            license: {
                label: 'nav.license',
                icon: 'description',
                to: '/license',
                order: 2,
            },
        },
    },
}

export default navigation
