import { defineAsyncView } from '@/core/util/facade'

export {
  mailService,
  type MailApproverOption,
  type MailDeliveryAgentOption,
  type MailDeliveryDetail,
  type MailDeliveryListItem,
  type MailDeliveryPage,
  type MailDeliveryQuery,
  type MailDeliveryStatus,
  type MailSendReceipt,
  type MailStatus,
} from './services/mailService'
export { CONNECTIONS_CHANGED_EVENT } from './contracts'
export { useConnectionStore } from './stores/connectionStore'
export { ManagedAgentSelect as McpCandidateAgent } from '@/app/agent'
export const ConnectionDialog = /* @__PURE__ */ defineAsyncView(() => import('./components/ConnectionList.vue'))
export const ConnectionList = ConnectionDialog
export const AuthorizationManager = /* @__PURE__ */ defineAsyncView(() => import('./components/AuthorizationManager.vue'))
