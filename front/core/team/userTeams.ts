import { defineAsyncComponent } from 'vue'
import type { UserTeams } from '@/core/user'
import { teamService } from './services/teamService'

export default {
  ...teamService,
  manager: defineAsyncComponent(() => import('./components/TeamManager.vue')),
} satisfies UserTeams
