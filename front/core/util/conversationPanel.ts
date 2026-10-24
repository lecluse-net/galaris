import type { Component } from 'vue'
import { modules as activeModules } from '@/modules'

export interface ConversationPanelContribution {
  component: Component
  hasDocumentConversation?: (documentId: string) => Promise<boolean>
}
const sources = import.meta.glob<{ default: ConversationPanelContribution }>('../../app/*/conversationPanel.ts', { eager: true })
const contribution = Object.entries(sources)
  .find(([path]) => activeModules.includes(`app/${path.split('/')[3]}`))?.[1].default
export const conversationPanel = contribution?.component
export const hasDocumentConversation = contribution?.hasDocumentConversation
