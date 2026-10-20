import type { RichContentContribution } from '@/core/util'
import { referenceId, referenceCardHtml, referenceDate } from '@/core/util'
import { chatService } from './services/chatService'
const idFrom = (uri: string) => referenceId(uri, 'room', '/chat', 'room')
export default {
  schemes: ['galaris'],
  canonical(value) { const id = idFrom(value); return id ? `galaris://room/${id}` : null },
  async search(query) {
    const page = await chatService.rooms(1, 50, query)
    return page.items.map(room => ({ uri: `galaris://room/${room.id}`, title: room.label || room.external_id, context: room.agent_name }))
  },
  href(uri) { const id = idFrom(uri); return id ? `/chat?room=${id}` : null },
  target(uri, title = '') { const id = idFrom(uri); return id ? { kind: 'room', id, title } : null },
  async title(uri) { const id = idFrom(uri); if (!id) return uri; const room = await chatService.room(id); return room.label || room.external_id },
  async card(uri, _agentId, formatting) {
    const id = idFrom(uri)
    if (!id) throw new Error('Invalid Room reference')
    const room = await chatService.room(id)
    return referenceCardHtml(`galaris://room/${id}`, room.label || room.external_id, [room.agent_name, room.messenger_label, room.conversation_type, referenceDate(room.last_message?.created_at, formatting)])
  },
} satisfies RichContentContribution
