import { defineAsyncView } from '@/core/util'

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
export { CONNECTIONS_CHANGED_EVENT } from './events'
export { useConnectionStore } from './stores/connectionStore'
export { default as McpCandidateAgent } from './components/McpCandidateAgent.vue'
export const ConnectionDialog = defineAsyncView(() => import('./components/ConnectionList.vue'))
