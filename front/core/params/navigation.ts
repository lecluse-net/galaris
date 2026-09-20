import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
import { preferenceSections, preferenceSectionPath } from './presentation'

const preferenceChildren: NavigationTree = Object.fromEntries(preferenceSections.map((section, index) => [
    section.key,
    {
        label: section.titleKey,
        description: section.descriptionKey,
        icon: section.icon,
        order: index,
        to: preferenceSectionPath(section.slug),
        privileges: [privileges.PARAMS_ACCESS],
    },
]))

const navigation: NavigationTree = {
    admin: {
        children: {
            params: {
                label: 'nav.params',
                icon: 'settings',
                to: '/params',
                order: 10,
                description: 'nav.params_desc',
                privileges: [privileges.PARAMS_ACCESS],
                children: preferenceChildren,
            }
        }
    }
}

export default navigation
