import { getAgentSelection } from '@/app/agent'
import { teamService } from '@/core/team'

/** Assemble agent display metadata without coupling shared owner controls to Agent. */
export async function readMemberships(kind: string, signal: AbortSignal) {
  if (kind === 'agent') return await getAgentSelection('management', signal)
  if (kind === 'user') return await teamService.humanSelection(signal)
  return []
}
