import { api } from '@/core/api'

export const budgetPeriods = ['session', 'weekly', 'monthly'] as const
export type BudgetPeriod = typeof budgetPeriods[number]

export interface Envelope {
  period: BudgetPeriod
  starts_at: string | null
  resets_at: string | null
  limit: string | null
  granted: string
  spent: string
  exhausted: boolean
}

export function canGrantCredit(envelope: Envelope): boolean {
  return envelope.limit !== null && envelope.starts_at !== null
}

export interface CreditRequest {
  id: string
  period: BudgetPeriod
  amount: string
  status: 'pending' | 'approved' | 'rejected'
}

export interface AccountBudget {
  user_id: number
  label: string
  envelopes: Envelope[]
  requests: CreditRequest[]
}

export interface ManagedAccountBudget extends AccountBudget { can_configure: boolean; can_manage_credits: boolean }
interface BudgetOverview { account: AccountBudget; can_configure_own: boolean; can_request_credit: boolean }
interface AccountsPage { items: ManagedAccountBudget[]; total: number }
export const budgetChanged = 'galaris:inference-budget-changed'

export const budgetService = {
  async me(signal?: AbortSignal): Promise<BudgetOverview> {
    return (await api.get<BudgetOverview>('/llm-budget/me', { signal })).data
  },
  async managed(page: number, pageSize: number, signal?: AbortSignal): Promise<AccountsPage> {
    return (await api.get<AccountsPage>('/llm-budget/managed', {
      params: { page, page_size: pageSize }, signal,
    })).data
  },
  async request(period: BudgetPeriod, amount: string) {
    await api.post('/llm-budget/requests', { period, amount })
  },
  async grant(user: number, period: BudgetPeriod, amount: string, operationId: string) {
    await api.post(`/llm-budget/grants/${user}`, { period, amount, operation_id: operationId })
  },
  async review(id: string, decision: 'approved' | 'rejected') {
    await api.post(`/llm-budget/requests/${id}/review`, { decision })
  },
  async policy(user: number, amounts: Record<BudgetPeriod, string | null>) {
    await api.put(`/llm-budget/policies/${user}`, {
      session_limit: amounts.session, weekly_limit: amounts.weekly, monthly_limit: amounts.monthly,
    })
  },
}
