import type { NavigationTree } from '@/core/navigation'
import { labSections, labSectionPath } from './presentation'
import { allLabPrivileges, labSectionPrivileges } from './access'

const labChildren: NavigationTree = Object.fromEntries(labSections.map((section, index) => [
  section.key,
  {
    label: section.titleKey,
    icon: section.icon,
    order: index,
    to: labSectionPath(section.slug),
    privileges: [...labSectionPrivileges[section.key]],
  },
]))

const navigation: NavigationTree = {
  admin: {
    children: {
      lab: {
        label: 'nav.lab',
        description: 'nav.lab_desc',
        icon: 'science',
        order: 20,
        to: '/lab',
        privileges: allLabPrivileges,
        children: labChildren,
      },
    },
  },
}

export default navigation
