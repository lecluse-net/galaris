import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export interface MailConnectionStatus {
  connection_id: number
  email_address: string
  imap_ok: boolean
  smtp_ok: boolean
  mailboxes: number
  sent_mailbox?: string | null
  trash_mailbox?: string | null
}

export interface MailConnectionTestResult {
  connection_id: number
  status: MailConnectionStatus
}

export interface MailStatus {
  enabled: boolean
}

export type MailDeliveryStatus =
  | 'pending_approval'
  | 'claimed'
  | 'submitting'
  | 'sent'
  | 'rejected'
  | 'uncertain'
  | 'error'

export type MailDeliveryKind = 'send' | 'reply' | 'forward'

export interface MailDeliveryListItem {
  id: string
  connection_id: number | null
  agent_id: number | null
  agent_label: string
  sender_address: string
  delivery_kind: MailDeliveryKind
  to_addresses: string[]
  cc_addresses: string[]
  bcc_addresses: string[]
  subject: string
  body_preview: string
  attachment_count: number
  status: MailDeliveryStatus
  approval_required: boolean
  approver_user_id: number | null
  approver_label: string | null
  reviewed_by_user_id: number | null
  reviewed_by_label: string | null
  reviewed_at: string | null
  rejection_reason: string | null
  accepted_recipients: number
  rejected_recipients: number
  created_at: string
  updated_at: string
  sent_at: string | null
  can_review: boolean
}

export interface MailDeliveryDetail extends MailDeliveryListItem {
  body: string
  html_body: string | null
  attachments: Array<{ filename?: string; media_type?: string; size?: number }>
  message_id: string
  disclosure_version: string
  smtp_response_code: number | null
}

export interface MailDeliveryPage {
  items: MailDeliveryListItem[]
  total: number
  offset: number
  limit: number
}

export interface MailDeliveryAgentOption {
  id: number
  label: string
}

export interface MailApproverOption {
  id: number
  label: string
  email: string
}

export interface MailSendReceipt {
  delivery_id: string
  status: MailDeliveryStatus
  message_id: string
  accepted_recipients: number
  rejected_recipients: number
  disclosure_version: string
  detail: string
}

export interface MailDeliveryQuery {
  scope: 'pending' | 'history' | 'all'
  agent_id?: number
  search?: string
  offset?: number
  limit?: number
}

export const mailService = {
  status(): Promise<AxiosResponse<MailStatus>> {
    return api.get('/mail/status')
  },
  testConnection(connectionId: number): Promise<AxiosResponse<MailConnectionTestResult>> {
    return api.post(`/mail/connections/${connectionId}/test`)
  },
  listDeliveries(query: MailDeliveryQuery): Promise<AxiosResponse<MailDeliveryPage>> {
    return api.get('/mail/outbound', { params: query })
  },
  listDeliveryAgents(): Promise<AxiosResponse<MailDeliveryAgentOption[]>> {
    return api.get('/mail/outbound/agents')
  },
  listApprovers(): Promise<AxiosResponse<MailApproverOption[]>> {
    return api.get('/mail/approvers')
  },
  getDelivery(deliveryId: string): Promise<AxiosResponse<MailDeliveryDetail>> {
    return api.get(`/mail/outbound/${deliveryId}`)
  },
  approveDelivery(deliveryId: string): Promise<AxiosResponse<MailSendReceipt>> {
    return api.post(`/mail/outbound/${deliveryId}/approve`)
  },
  rejectDelivery(deliveryId: string, reason: string): Promise<AxiosResponse<MailDeliveryDetail>> {
    return api.post(`/mail/outbound/${deliveryId}/reject`, { reason })
  },
}
