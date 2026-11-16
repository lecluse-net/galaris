import { api } from '@/core/api'

export default { key: 'incidents', run: () => api.delete<void>('/incidents/cleanup') }
