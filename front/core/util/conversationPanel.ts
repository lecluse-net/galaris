import type { Component } from 'vue'
import { modules as activeModules } from '@/modules'

export interface ConversationPanelContribution { component: Component }
const sources = import.meta.glob<{ default: ConversationPanelContribution }>('../../app/*/conversationPanel.ts', { eager: true })
export const conversationPanel = Object.entries(sources)
  .find(([path]) => activeModules.includes(`app/${path.split('/')[3]}`))?.[1].default.component
