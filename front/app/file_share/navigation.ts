import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'

const navigation: NavigationTree = {
  knowledge: {
    children: {
      files: { label: 'nav.files', description: 'nav.files_desc', icon: 'folder_open',
        to: '/files', order: 15, privileges: [privileges.FILE_ACCESS, privileges.FILE_EDIT] },
    },
  },
  admin: {
    children: {
      params: {
        children: {
          files: { label: 'nav.files', description: 'files.settingsDescription', icon: 'folder_open',
            to: '/params/files', order: 4, privileges: [privileges.FILE_INDEX_ACCESS, privileges.FILE_INDEX_RUN] },
        },
      },
    },
  },
}
export default navigation
