import type { NavigationTree } from '@/core/navigation'

const navigation: NavigationTree = {
  admin: {
    children: {
      users: {
        label: 'nav.users',
        icon: 'people',
        order: 40,
        to: '/user/users',
        description: 'nav.users_desc',
        privileges: ['READ_USER', 'CREATE_USER', 'UPDATE_USER', 'DELETE_USER'], // This module loads before authorize.
      }
    }
  }
}

export default navigation
