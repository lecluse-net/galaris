import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
const navigation: NavigationTree = {
  knowledge: { children: { calendars: { label: 'calendars.title', description: 'calendars.description', icon: 'calendar_month', order: 21, to: '/calendar', privileges: [privileges.CALENDAR_ACCESS, privileges.CALENDAR_EDIT] } } },
}
export default navigation
