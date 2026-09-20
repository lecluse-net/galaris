import { defineAsyncComponent } from 'vue'
import type { TeamContribution } from '@/core/team'
import { teamService } from './services/teamService'

export default {
  key: 'agents',
  labelKey: 'team.agents',
  component: defineAsyncComponent(() => import('./components/TeamAgentMembers.vue')),
  privilege: 'TEAM_ACCESS',
  load: teamService.agents,
  setMembership: teamService.membership,
} satisfies TeamContribution
