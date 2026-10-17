import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  knowledge: {
    children: {
      files: { label: 'nav.files', description: 'nav.files_desc', icon: 'folder_open',
        to: '/files', order: 15, privileges: [privileges.MEMORY_ACCESS] },
    },
  },
}
export default navigation
