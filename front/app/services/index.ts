export { default as SystemServiceIcon } from './components/SystemServiceIcon.vue'
export { default as ServiceIdentityIcon } from './components/ServiceIdentityIcon.vue'
export type { ServiceIcon } from './services/serviceApi'
export { default as ServiceOriginBadge } from './components/ServiceOriginBadge.vue'
export { default as ServiceFilterSelect } from './components/ServiceFilterSelect.vue'
export { default as ConnectionParamInput } from './components/ConnectionParamInput.vue'
export type { Service, ConnectionParamDef, ConnectionParamOption } from './services/serviceApi'
import { defineAsyncView } from '@/core/util/facade'

export const ServicesList = /* @__PURE__ */ defineAsyncView(() => import('./components/ServicesList.vue'))
