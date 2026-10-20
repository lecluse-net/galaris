import type { RichContentContribution } from '@/core/util'
import { referenceId, referenceCardHtml, referenceDate, referenceStatus } from '@/core/util'
import { voiceConversationService } from './services/voiceConversationService'
const turnId = (uri: string) => referenceId(uri, 'voice', '/task', 'voice_turn_id')
const sessionId = (uri: string) => referenceId(uri, 'voice_session', '/task', 'voice_session_id')
export default {
  schemes: ['galaris'],
  canonical(value) { const turn = turnId(value), session = sessionId(value); return turn ? `galaris://voice/${turn}` : session ? `galaris://voice_session/${session}` : null },
  async search(query, formatting) {
    const page = await voiceConversationService.list({ search: query, pageSize: 50 })
    return page.items.flatMap(session => [
      { uri: `galaris://voice_session/${session.id}`, title: formatting.t('voice.history.callSummary', { count: session.turn_count }), context: [session.agent_name, referenceDate(session.started_at, formatting)].filter(Boolean).join(' · ') },
      ...session.turns.map(turn => ({ uri: `galaris://voice/${turn.id}`, title: formatting.t('voice.history.turnLabel', { sequence: turn.sequence }), context: [session.agent_name, referenceDate(turn.started_at, formatting)].filter(Boolean).join(' · ') })),
    ])
  },
  href(uri) { const turn = turnId(uri), session = sessionId(uri); return turn ? `/task?voice_turn_id=${turn}` : session ? `/task?voice_session_id=${session}` : null },
  target(uri, title = '') { const turn = turnId(uri), session = sessionId(uri); return turn ? { kind: 'voice', id: turn, title } : session ? { kind: 'voice_session', id: session, title } : null },
  async title(uri, _agentId, formatting) {
    const turn = turnId(uri), session = sessionId(uri)
    if (turn) { const value = await voiceConversationService.getTurn(turn); return formatting.t('voice.history.turnLabel', { sequence: value.sequence }) }
    if (session) { const value = await voiceConversationService.get(session); return formatting.t('voice.history.callSummary', { count: value.turn_count }) }
    return uri
  },
  async card(uri, _agentId, formatting) {
    const turn = turnId(uri), session = sessionId(uri)
    if (turn) {
      const value = await voiceConversationService.getTurn(turn)
      return referenceCardHtml(`galaris://voice/${turn}`, formatting.t('voice.history.turnLabel', { sequence: value.sequence }),
        [value.agent_name, referenceDate(value.started_at, formatting), value.transport_kind, referenceStatus('voice.history.turnStatuses', value.status, formatting), value.room_id])
    }
    if (!session) throw new Error('Invalid Voice reference')
    const value = await voiceConversationService.get(session)
    return referenceCardHtml(`galaris://voice_session/${session}`, formatting.t('voice.history.callSummary', { count: value.turn_count }),
      [value.agent_name, referenceDate(value.started_at, formatting), value.transport_kind, referenceStatus('voice.history.statuses', value.status, formatting), value.room_id])
  },
} satisfies RichContentContribution
