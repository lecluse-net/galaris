import { api } from '@/core/api'
import type { GoalCategory } from '../types'

export const categoryService = {
  async list(): Promise<GoalCategory[]> {
    return (await api.get<GoalCategory[]>('/goals/categories')).data
  },
  async create(label: string): Promise<GoalCategory> {
    return (await api.post<GoalCategory>('/goals/categories', { label })).data
  },
  async update(id: number, label: string): Promise<GoalCategory> {
    return (await api.put<GoalCategory>(`/goals/categories/${id}`, { label })).data
  },
  async delete(id: number): Promise<void> {
    await api.delete(`/goals/categories/${id}`)
  },
}
