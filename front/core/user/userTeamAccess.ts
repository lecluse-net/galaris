import { modules } from '@/modules'

export interface UserTeams {
  list(userId?: number): Promise<{ id: number; name: string }[]>
  membership(teamId: number, userId: number, present: boolean): Promise<void>
}

const contributions = import.meta.glob<{ default: UserTeams }>('../*/userTeams.ts', { eager: true })
export const userTeams = Object.entries(contributions)
  .find(([path]) => modules.includes(`core/${path.split('/')[1]}`))
  ?.[1].default
