import { api } from '@/core/api'
import type { LLMCall, LLMCallPage } from '../types'


class LLMCallService {
  async getByRuns(taskIds: string[], runIds: string[]): Promise<LLMCall[]> {
    const params = new URLSearchParams({ limit: '500' })
    taskIds.forEach(id => params.append('task_ids', id))
    runIds.forEach(id => params.append('agent_run_ids', id))
    return (await api.get<LLMCall[]>(`/llm-calls?${params}`)).data
  }

  async getRecent(limit: number = 100): Promise<LLMCall[]> {
    const response = await api.get('/llm-calls', { params: { limit } })
    return response.data
  }

  async getRunning(
    limit: number = 10,
    dateFrom?: string | null,
    dateTo?: string | null,
  ): Promise<LLMCall[]> {
    const response = await api.get('/llm-calls/running', {
      params: { limit, date_from: dateFrom || undefined, date_to: dateTo || undefined },
    })
    return response.data
  }

  async getHistory(
    page: number = 1,
    pageSize: number = 50,
    errorsOnly: boolean = false,
    dateFrom?: string | null,
    dateTo?: string | null,
  ): Promise<LLMCallPage> {
    const response = await api.get<LLMCallPage>('/llm-calls/history', {
      params: {
        page,
        page_size: pageSize,
        errors_only: errorsOnly,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      },
    })
    return response.data
  }

  async getByTask(taskId: string): Promise<LLMCall[]> {
    const response = await api.get(`/llm-calls?task_id=${encodeURIComponent(taskId)}`)
    return response.data
  }

  async cleanup(): Promise<void> {
    await api.delete('/llm-calls/cleanup')
  }

  async delete(callId: string): Promise<void> {
    await api.delete(`/llm-calls/${encodeURIComponent(callId)}`)
  }
}

export const llmCallService = new LLMCallService()
