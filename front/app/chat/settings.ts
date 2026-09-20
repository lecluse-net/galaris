import type { BridgeSettingsContribution } from '@/core/params/settingsTypes'
import { chatAvailable, refreshChatAvailability } from './availability'

export default {
  area: 'messaging',
  kind: 'internal',
  label: 'Chat',
  icon: 'forum',
  guideKey: 'messagingProviders.chat.guide',
  stepsKey: 'messagingProviders.chat.steps',
  docsUrl: '/chat',
  fields: [
    { name: 'WEB_PUSH_VAPID_SUBJECT', labelKey: 'webPushSettings.subject', descriptionKey: 'webPushSettings.subjectHint', input: 'text' },
    { name: 'WEB_PUSH_DELAY_SECONDS', labelKey: 'webPushSettings.delay', descriptionKey: 'webPushSettings.delayHint', input: 'number', min: 1, max: 30, step: 0.5 },
    { name: 'GALARIS_INTERNAL_MESSENGER_MAX_BYTES', labelKey: 'storageSettings.chatMaxBytes', input: 'integer', sizeUnit: 'bytes', min: 1000000 },
  ],
  isAvailable: () => chatAvailable.value === true,
  refreshAvailability: refreshChatAvailability,
} satisfies BridgeSettingsContribution
