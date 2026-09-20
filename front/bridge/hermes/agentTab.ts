import type { AgentDriverTabContribution } from '@/app/agent/driverTabs'
import HermesAgentConfiguration from './components/HermesAgentConfiguration.vue'

export default {
  driver: 'hermes',
  name: 'hermes',
  labelKey: 'hermes.agentTab',
  icon: 'smart_toy',
  component: HermesAgentConfiguration,
} satisfies AgentDriverTabContribution
