import type { ConnectionParamOption } from './services/serviceApi'

export interface ServiceParameterChoices {
  loadUserOptions(): Promise<ConnectionParamOption[]>
}

// Cross-domain composition follows the same application boundary as resource details.
const providers = import.meta.glob<ServiceParameterChoices>('../../../serviceParameterChoices.ts')

export async function loadServiceUserOptions(): Promise<ConnectionParamOption[]> {
  const provider = Object.values(providers)[0]
  if (!provider) throw new Error('Service parameter choices provider unavailable')
  return (await provider()).loadUserOptions()
}
