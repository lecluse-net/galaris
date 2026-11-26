import { privilegeCatalogueEnabled, privileges } from '@/core/authorize'
import { modules } from '@/modules'

const teamsEnabled = modules.includes('core/team')

export const userAdministrationTabs = [
  { name: 'users', labelKey: 'usersAdmin.tabUsers', icon: 'people',
    privileges: [privileges.READ_USER, privileges.CREATE_USER, privileges.UPDATE_USER, privileges.DELETE_USER] },
  { name: 'teams', labelKey: 'team.title', icon: 'groups',
    privileges: [privileges.TEAM_ACCESS] },
  { name: 'roles', labelKey: 'authorize.tabRoles', icon: 'security',
    privileges: [privileges.READ_ROLE, privileges.MANAGE_ROLE] },
  { name: 'privileges', labelKey: 'authorize.tabPrivileges', icon: 'vpn_key',
    privileges: [privileges.READ_PRIVILEGE, privileges.MANAGE_PRIVILEGE] },
] as const

export function visibleUserAdministrationTabs(hasAnyPrivilege: (codes: readonly string[]) => boolean) {
  return userAdministrationTabs.filter(tab =>
    (tab.name !== 'privileges' || privilegeCatalogueEnabled)
    && (tab.name !== 'teams' || teamsEnabled)
    && hasAnyPrivilege(tab.privileges))
}
