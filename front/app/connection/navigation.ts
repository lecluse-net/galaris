import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
import { isMailNavigationVisible } from './availability'

const navigation: NavigationTree = {
  monitor: {
    children: {
      calendars: {
        label: 'calendars.title', description: 'calendars.description', icon: 'calendar_month',
        order: 32, to: '/connection/calendars',
        privileges: [privileges.CALENDAR_ACCESS, privileges.CALENDAR_EDIT],
      },
      permissions: {
        label: 'permissions.title', description: 'permissions.description', icon: 'verified_user',
        order: 31, to: '/connection/permissions',
        privileges: [privileges.PERMISSION_ACCESS, privileges.PERMISSION_DECIDE, privileges.PERMISSION_REVOKE],
      },
      mailJournal: {
        label: 'nav.mailJournal',
        icon: 'outbox',
        order: 30,
        to: '/connection/mail',
        description: 'nav.mailJournal_desc',
        privileges: [privileges.MAIL_ACCESS, privileges.MAIL_EDIT],
        visible: isMailNavigationVisible,
      },
    },
  },
}

export default navigation
