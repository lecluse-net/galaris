import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
import { useBrowserSettingsStore } from './stores/browserSettingsStore'

export default {
    admin: { children: { params: { children: {
        browser: {
            label: 'browserSettings.title',
            description: 'browserSettings.subtitle',
            icon: 'web',
            to: '/browser/settings',
            order: 10,
            privileges: [privileges.PARAMS_ACCESS, privileges.PARAMS_EDIT],
            visible: () => useBrowserSettingsStore().available === true,
        },
    } } } },
} satisfies NavigationTree
