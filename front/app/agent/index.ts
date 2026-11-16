import { defineAsyncView } from '@/core/util/facade'
export const AgentAuxiliaryDialogs = /* @__PURE__ */ defineAsyncView(() => import('./components/AgentAuxiliaryDialogs.vue'))
export const AvatarGenerationDialog = /* @__PURE__ */ defineAsyncView(() => import('./components/AvatarGenerationDialog.vue'))
export { default as AgentAvatar } from './components/AgentAvatar.vue'
export { agentResourceId } from './resourceUri'
export { default as AgentSelect } from './components/AgentSelect.vue'
export { default as ManagedAgentSelect } from './components/ManagedAgentSelect.vue'
export { default as AgentTeamSelect } from './components/AgentTeamSelect.vue'
export { useAgentStore } from './stores/agentStore'
export { useAgentChoices } from './composables/useAgentChoices'
export { useAgentSelectionStore } from './stores/agentSelectionStore'
export type { Agent } from './services/agentService'
export { getAgentSelection } from './services/agentSelectionService'
export type { AgentSelectionOption } from './services/agentSelectionService'

export const AgentMcpPanel = /* @__PURE__ */ defineAsyncView(() => import('./components/AgentMcpPanel.vue'))
