import type { MemberTeam, MemberTeams } from '@/core/util/facade'
import type { OwnerOption } from './owners'

export function groupOwnersByTeam(
  options: readonly OwnerOption[], memberships: Record<'agent' | 'user', readonly MemberTeams[]>, withoutTeam: string,
) {
  const members = {
    agent: new Map(memberships.agent.map(member => [member.id, member.teams ?? []])),
    user: new Map(memberships.user.map(member => [member.id, member.teams ?? []])),
  }
  const buckets = new Map<number | null, { team: MemberTeam | null; agent: OwnerOption[]; user: OwnerOption[] }>()
  for (const option of options) {
    const teams = members[option.kind].get(option.id) ?? []
    for (const team of teams.length ? teams : [null]) {
      const key = team?.id ?? null
      const bucket = buckets.get(key) ?? { team, agent: [], user: [] }
      bucket[option.kind].push(option)
      buckets.set(key, bucket)
    }
  }
  return [...buckets.values()].sort((a, b) => {
    if (!a.team) return b.team ? 1 : 0
    if (!b.team) return -1
    return a.team.order - b.team.order || a.team.id - b.team.id
  }).map(bucket => ({
    key: String(bucket.team?.id ?? 'none'), label: bucket.team?.name ?? withoutTeam,
    groups: (['agent', 'user'] as const).filter(kind => bucket[kind].length).map(kind => ({
      kind, key: `${bucket.team?.id ?? 'none'}:${kind}`, items: bucket[kind],
    })),
  }))
}
