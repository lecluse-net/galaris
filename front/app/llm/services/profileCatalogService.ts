import api from '@/core/api'

interface ProfileCatalog {
  data: { id: string }[]
}

export async function getProfileModelSelectors(signal: AbortSignal): Promise<string[]> {
  const response = await api.get<ProfileCatalog>('/profile/models', { signal })
  return response.data.data.map(model => model.id)
}
