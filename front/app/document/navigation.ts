import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
const navigation: NavigationTree = { knowledge: { children: {
      documents: {
        label: 'nav.documents',
        description: 'nav.documents_desc',
        icon: 'description',
        order: 10,
        to: '/documents',
        privileges: [privileges.DOCUMENT_ACCESS, privileges.DOCUMENT_EDIT, privileges.DOCUMENT_ADMIN],
      },
} } }
export default navigation
