export interface MemberTeam { id: number; name: string; order: number }
export interface MemberTeams { id: number; teams?: MemberTeam[] }

export interface MemberChoice {
  value: number | null
  label: string
  hasAvatar?: boolean
  caption?: string
  disable?: boolean
}

export function groupMemberOptions(
  options: readonly MemberChoice[], agents: readonly MemberTeams[], withoutTeam: string,
): (MemberChoice & { teamHeading?: string })[] {
  const byId = new Map(agents.map(agent => [agent.id, agent]))
  const groups = new Map<number, { team: MemberTeam; options: MemberChoice[] }>()
  const unassigned: MemberChoice[] = [], unknown: MemberChoice[] = [], neutral: MemberChoice[] = []
  for (const option of options) {
    if (option.value === null) { neutral.push(option); continue }
    const agent = byId.get(option.value)
    if (!agent) { unknown.push(option); continue }
    if (!agent.teams?.length) { unassigned.push(option); continue }
    for (const team of agent.teams) {
      const group = groups.get(team.id) ?? { team, options: [] }
      group.options.push(option)
      groups.set(team.id, group)
    }
  }
  // Incomplete metadata must not reshuffle an otherwise ungrouped catalogue.
  if (groups.size === 0 && unknown.length > 0) return [...options]
  const section = (choices: MemberChoice[], heading: string) => choices.map((option, index) => ({
    ...option, ...(index === 0 ? { teamHeading: heading } : {}),
  }))
  return [
    ...neutral,
    ...unknown,
    ...[...groups.values()].sort((a, b) => a.team.order - b.team.order || a.team.id - b.team.id)
      .flatMap(group => section(group.options, group.team.name)),
    ...section(unassigned, withoutTeam),
  ]
}
