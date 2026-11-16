export { default as VoiceConversationDetailView } from './components/VoiceConversationDetail.vue'
export { voiceConversationService } from './services/voiceConversationService'
export type { VoiceConversationDetail, VoiceConversationTurn } from './types'
import { defineAsyncView } from '@/core/util/facade'
export const VoiceCallHistory = /* @__PURE__ */ defineAsyncView(() => import('./components/VoiceCallHistory.vue'))
