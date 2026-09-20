import type { NavigationTree } from '@/core/navigation'
export default { admin: { children: { teams: { label: 'team.title', icon: 'groups', to: '/team', order: 45, description: 'team.intro', privileges: ['TEAM_ACCESS'] } } } } satisfies NavigationTree
