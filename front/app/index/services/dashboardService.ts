import api from '@/core/api'

export interface DashboardTotals {
  tasks: number
  successful_tasks: number
  task_errors: number
  llm_calls: number
  llm_errors: number
  incidents: number
  tokens: number
  cost: number
  inference_cost: number
  average_llm_duration: number
  task_success_rate: number
  llm_success_rate: number
}

export interface DailyLlmUsage {
  date: string
  llm_key: string
  llm_label: string
  provider_name: string
  calls: number
  errors: number
  input_tokens: number
  output_tokens: number
  tokens: number
  cost: number
  inference_cost: number
}

export interface AgentUsage {
  agent_id: number
  agent_name: string
  job_title: string | null
  has_avatar: boolean
  tasks: number
  successful_tasks: number
  task_errors: number
  llm_calls: number
  llm_errors: number
  incidents: number
  tokens: number
  cost: number
  average_llm_duration: number
  task_success_rate: number
}

export interface DashboardData {
  month: string
  available_months: string[]
  totals: DashboardTotals
  previous_totals: DashboardTotals
  daily_usage: DailyLlmUsage[]
  agents: AgentUsage[]
}

export const dashboardService = {
  async getDashboard(month: string): Promise<DashboardData> {
    const response = await api.get<DashboardData>('/dashboard', { params: { month } })
    return response.data
  },
}
