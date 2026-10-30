import { api } from '@/core/api'

export interface MailMessage {
  ref: string
  subject: string
  from_name: string
  from_address: string
  to_addresses: string[]
  cc_addresses: string[]
  date: string | null
  seen: boolean
  flagged: boolean
  body: string
  body_total: number
  body_start: number
  body_end: number
  next_body_offset: number | null
  attachments: { uri: string; filename: string; media_type: string; size: number; part_id: string }[]
}

export const mailBrowserService = {
  async message(agentId: number, reference: string, bodyOffset = 0, signal?: AbortSignal): Promise<MailMessage> {
    return (await api.get<MailMessage>('/mail/browser/message', {
      params: { agent_id: agentId, message_ref: reference, body_offset: bodyOffset }, signal,
    })).data
  },
}
