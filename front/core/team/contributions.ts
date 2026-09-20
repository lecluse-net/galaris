import type { Component } from 'vue'
import { modules as activeModules } from '@/modules'

export interface TeamMember { id: number; label: string; team_ids: number[]; has_avatar: boolean }
export interface TeamContribution {
  key: string
  labelKey: string
  component: Component
  privilege: string
  load(): Promise<TeamMember[]>
  setMembership(teamId: number, memberId: number, present: boolean): Promise<void>
}
export interface LoadedTeamContribution { definition: TeamContribution; members: TeamMember[] }
const sources = import.meta.glob<{ default: TeamContribution }>('../../app/*/team.ts', { eager: true })
export const teamContributions = Object.entries(sources)
  .filter(([path]) => activeModules.includes(`app/${path.split('/')[3]}`))
  .map(([, module]) => module.default)
