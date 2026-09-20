import type { Component } from 'vue'

export interface AgentDriverTabContribution {
  driver: string
  name: string
  labelKey: string
  icon: string
  component: Component
}

interface AgentDriverTabModule {
  default: AgentDriverTabContribution
}

const modules = import.meta.glob<AgentDriverTabModule>(
  '../../bridge/*/agentTab.ts',
  { eager: true },
)

export const agentDriverTabs = Object.values(modules).map(module => module.default)

export function getAgentDriverTab(driver: string): AgentDriverTabContribution | undefined {
  return agentDriverTabs.find(contribution => contribution.driver === driver)
}
