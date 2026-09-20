import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export const logCleanupService = {
  cleanupIncidents(): Promise<AxiosResponse<void>> {
    return api.delete('/incidents/cleanup')
  },
}
