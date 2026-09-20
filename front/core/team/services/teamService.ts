import api from '@/core/api'

export interface TeamWrite { name: string; description: string }
export interface Team extends TeamWrite { id: number; order: number; human_count: number; human_members: Human[] }
export interface Human { id: number; label: string; active: boolean; avatar_url: string | null }
export const teamService = {
  async list(): Promise<Team[]> { return (await api.get<Team[]>('/teams')).data },
  async save(data: TeamWrite, id?: number): Promise<Team> {
    return (id ? await api.put<Team>(`/teams/${id}`, data) : await api.post<Team>('/teams', data)).data
  },
  async remove(id: number): Promise<void> { await api.delete(`/teams/${id}`) },
  async move(id: number, target: number, after: boolean): Promise<void> {
    await api.put(`/teams/${id}/position`, { target_team_id: target, after })
  },
  async humans(search = ''): Promise<Human[]> { return (await api.get<Human[]>('/teams/humans', { params: { search } })).data },
  async members(id: number): Promise<Human[]> { return (await api.get<Human[]>(`/teams/${id}/humans`)).data },
  async membership(team: number, human: number, present: boolean): Promise<void> {
    await api.put(`/teams/${team}/humans/${human}`, { present })
  },
}
