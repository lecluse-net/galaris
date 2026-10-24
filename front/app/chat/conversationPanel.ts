import { defineAsyncComponent } from 'vue'
import type { ConversationPanelContribution } from '@/core/util'

export default {
  component: defineAsyncComponent(() => import('./components/DocumentConversationPanel.vue')),
} satisfies ConversationPanelContribution
