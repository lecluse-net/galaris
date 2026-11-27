import { modules } from '@/modules'
import type { Component } from 'vue'

export interface UserTeams {
  manager: Component
  list(userId?: number): Promise<{ id: number; name: string; manager_user_id: number | null }[]>
  membership(teamId: number, userId: number, present: boolean): Promise<void>
  assignManager(teamId: number, userId: number): Promise<void>
}

const contributions = import.meta.glob<{ default: UserTeams }>('../*/userTeams.ts', { eager: true })
export const userTeams = Object.entries(contributions)
  .find(([path]) => modules.includes(`core/${path.split('/')[1]}`))
  ?.[1].default
