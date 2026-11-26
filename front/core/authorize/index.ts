/**
 * Public API for core/authorize.
 * Exports authorization services, stores, and privilege constants.
 */

import { defineAsyncView } from '@/core/util/facade'

// Services
export { authorizeService } from './services/authorize.service'
export type { AssignmentWithRole, Role } from './services/authorize.service'
export { privilegeService } from './services/privilege.service'
export { localizedAuthorizeLabel } from './presentation'
export { configurePrivilegeCatalogue, privilegeCatalogueEnabled } from './access'

// Stores
export { useAuthorizeStore } from './stores/authorizeStore'
export { usePrivilegeStore } from './stores/privilegeStore'

// Components
export const UserPreferencesMenu = /* @__PURE__ */ defineAsyncView(() => import('./components/UserPreferencesMenu.vue'))
export const RoleManager = /* @__PURE__ */ defineAsyncView(() => import('./components/RoleManager.vue'))
export const PrivilegeListManager = /* @__PURE__ */ defineAsyncView(() => import('./components/PrivilegeListManager.vue'))

// Privilege constants generated from the backend.
export { privileges } from './definitions'
