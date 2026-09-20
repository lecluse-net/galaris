import { api } from '@/core/api'
import type { TaskActivitySnapshot } from '../activity'
import type { Task, TaskCreate, TaskUpdate, TaskWithAssignments, TaskFull, TaskPage } from '../types'
import type { Agent } from '@/app/agent/services/agentService'

export interface TaskBudget {
  enabled: boolean
  scope: 'goal' | 'task_tree'
  provider_hard_cap: boolean
  recorded_tokens: number
  recorded_cost: number
  active_phases: number
  reserved_tokens: number
  reserved_cost: number
  remaining_tokens: number | null
  remaining_cost: number | null
  remaining_seconds: number | null
}

export class TaskService {
  async getActivity(taskIds: string[]): Promise<TaskActivitySnapshot[]> {
    return (await api.post<TaskActivitySnapshot[]>('/tasks/activity', { task_ids: taskIds })).data
  }
  async getBudget(id: string): Promise<TaskBudget> {
    return (await api.get<TaskBudget>(`/tasks/${id}/budget`)).data
  }

  async getAll(skip: number = 0, limit: number = 100, agentId?: number): Promise<Task[]> {
    let url = `/tasks?skip=${skip}&limit=${limit}`
    if (agentId !== undefined) {
      url += `&agent_id=${agentId}`
    }
    const response = await api.get(url)
    return response.data
  }

  async getActive(limit: number = 10): Promise<Task[]> {
    const response = await api.get('/tasks/active', { params: { limit } })
    return response.data
  }

  async getById(id: string): Promise<TaskWithAssignments> {
    const response = await api.get(`/tasks/${id}`)
    return response.data
  }

  async getByIdWithAgent(id: string): Promise<{ task: TaskWithAssignments; agent?: Agent }> {
    const taskResponse = await api.get(`/tasks/${id}`)
    const task = taskResponse.data

    let agent: Agent | undefined
    if (task.agent_id) {
      try {
        const agentResponse = await api.get(`/agents/${task.agent_id}`)
        agent = agentResponse.data
      } catch (error) {
        console.warn(`Failed to fetch agent ${task.agent_id}:`, error)
      }
    }

    return { task, agent }
  }

  async getFull(id: string): Promise<TaskFull> {
    const response = await api.get(`/tasks/${id}/full`)
    return response.data
  }

  /** Planned child tasks in creation order. */
  async getChildren(id: string): Promise<Task[]> {
    const response = await api.get(`/tasks/${id}/children`)
    return response.data
  }

  async create(data: TaskCreate): Promise<Task> {
    const response = await api.post('/tasks', data, { headers: { 'X-Editorial-Profile-Version': '1' } })
    return response.data
  }

  async update(id: string, data: TaskUpdate): Promise<Task> {
    const response = await api.put(`/tasks/${id}`, data, { headers: { 'X-Editorial-Profile-Version': '1' } })
    return response.data
  }

  async delete(id: string): Promise<void> {
    await api.delete(`/tasks/${id}`)
  }

  /** Delete processed tasks without affecting active tasks. */
  async cleanup(): Promise<void> {
      await api.delete('/tasks/cleanup')
  }

  /** Start or continue a task in CREATE or paused state. */
  async run(id: string): Promise<Task> {
      const response = await api.post(`/tasks/${id}/run`)
      return response.data
  }

  async pause(id: string): Promise<Task> {
    const response = await api.post(`/tasks/${id}/pause`)
    return response.data
  }

  async resume(id: string): Promise<Task> {
    const response = await api.post(`/tasks/${id}/resume`)
    return response.data
  }

  async forceTerminate(id: string, expectedRevision: number): Promise<Task> {
    const response = await api.post(`/tasks/${id}/force-terminate`, {
      expected_revision: expectedRevision,
    })
    return response.data
  }

  async retry(id: string, expectedRevision: number): Promise<Task> {
    const response = await api.post(`/tasks/${id}/retry`, {
      expected_revision: expectedRevision,
    })
    return response.data
  }

  async restore(id: string): Promise<Task> {
    const response = await api.post(`/tasks/${id}/restore`)
    return response.data
  }

  async getRecent(
    skip: number = 0,
    limit: number = 15,
    agentId?: number,
    search?: string,
    errorsOnly: boolean = false,
    pausedOnly: boolean = false,
    dateFrom?: string | null,
    dateTo?: string | null,
    active?: boolean | null,
    topicId?: string | null,
  ): Promise<TaskPage> {
    let url = `/tasks/recent?skip=${skip}&limit=${limit}`
    if (agentId !== undefined) {
      url += `&agent_id=${agentId}`
    }
    if (search?.trim()) {
      url += `&q=${encodeURIComponent(search.trim())}`
    }
    if (errorsOnly) {
      url += '&errors_only=true'
    }
    if (pausedOnly) {
      url += '&paused_only=true'
    }
    if (dateFrom) {
      url += `&date_from=${encodeURIComponent(dateFrom)}`
    }
    if (dateTo) {
      url += `&date_to=${encodeURIComponent(dateTo)}`
    }
    if (active !== undefined && active !== null) {
      url += `&active=${active}`
    }
    if (topicId) {
      url += `&topic_id=${encodeURIComponent(topicId)}`
    }
    const response = await api.get(url)
    return response.data
  }
}

export const taskService = new TaskService()
