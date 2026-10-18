import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
import { settings } from '@/core/settings'

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
    admin: {
        children: {
            graphicReference: {
                label: 'graphicReference.title',
                description: 'graphicReference.description',
                icon: 'palette',
                to: '/graphic-reference',
                visible: () => settings.is_dev,
                order: 90,
            },
        },
    },
    pageFooter: {
        children: {
            about: {
                label: 'nav.about',
                icon: 'info',
                to: '/about',
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
