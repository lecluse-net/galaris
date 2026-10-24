import { defineAsyncComponent } from 'vue'
import type { ConversationPanelContribution } from '@/core/util'

export default {
  component: defineAsyncComponent(() => import('./components/DocumentConversationPanel.vue')),
  async hasDocumentConversation(documentId: string): Promise<boolean> {
    const { chatService } = await import('./services/chatService')
    return await chatService.documentConversation(documentId) !== null
  },
} satisfies ConversationPanelContribution
