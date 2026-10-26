import type { NavigationTree } from '@/core/navigation'
import { preferenceSections, preferenceSectionPath } from './presentation'
import { preferencePrivileges, sectionPrivileges } from './access'

const preferenceChildren: NavigationTree = Object.fromEntries(preferenceSections.map((section, index) => [
    section.key,
    {
        label: section.titleKey,
        description: section.descriptionKey,
        icon: section.icon,
        order: index,
        to: preferenceSectionPath(section.slug),
        privileges: sectionPrivileges(section.key),
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
                privileges: [...preferencePrivileges, 'BROWSER_CONFIG_ACCESS', 'BROWSER_CONFIG_EDIT', 'FILE_INDEX_ACCESS', 'FILE_INDEX_RUN'],
                children: preferenceChildren,
            }
        }
    }
}

export default navigation
