import type { NavigationTree } from '@/core/navigation'
import { usePrivilegeStore } from '@/core/authorize'
import { userAdministrationTabs, visibleUserAdministrationTabs } from './access'

const navigation: NavigationTree = {
  admin: {
    children: {
      users: {
        label: 'nav.users',
        icon: 'people',
        order: 40,
        to: '/users',
        description: 'nav.users_desc',
        privileges: userAdministrationTabs.flatMap(tab => [...tab.privileges]),
        visible: () => visibleUserAdministrationTabs(usePrivilegeStore().hasAnyPrivilege).length > 0,
      }
    }
  }
}

export default navigation
