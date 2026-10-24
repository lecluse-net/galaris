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
                privileges: [privileges.DASHBOARD_ACCESS],
            },
        },
    },
    developers: {
        visible: () => settings.is_dev,
        children: {
            graphicReference: {
                label: 'graphicReference.title',
                description: 'graphicReference.description',
                icon: 'palette',
                to: '/graphic-reference',
                order: 10,
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
