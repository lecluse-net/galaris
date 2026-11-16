import { mailService } from '@/app/connection'
import type { ServiceParameterChoices } from '@/app/services/contracts'

// The Mail domain owns eligibility and authorization; the parameter editor stays generic.
export const loadUserOptions: ServiceParameterChoices['loadUserOptions'] = async () => {
  const { data } = await mailService.listApprovers()
  return data.map(user => ({ value: String(user.id), label: user.label === user.email ? user.email : `${user.label} · ${user.email}` }))
}
