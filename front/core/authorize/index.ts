/**
 * Public API for core/authorize.
 * Exports authorization services, stores, and privilege constants.
 */

// Services
export { authorizeService } from './services/authorize.service'
export { privilegeService } from './services/privilege.service'
export { localizedAuthorizeLabel } from './presentation'

// Stores
export { useAuthorizeStore } from './stores/authorizeStore'
export { usePrivilegeStore } from './stores/privilegeStore'

// Components
export { default as UserPreferencesMenu } from './components/UserPreferencesMenu.vue'

// Privilege constants generated from the backend.
export { privileges } from './definitions'
