/**
 * API service for onboarding.
 *
 * Checks module configuration and determines whether onboarding help blocks
 * should be displayed on the home page.
 */
import api from '@/core/api'

/**
 * Response indicating whether an onboarding block should be displayed.
 */
export interface OnboardingStatusResponse {
  /** Whether the user has the privilege and the module contains no data. */
  show: boolean
  /** Whether the user has the required privilege. */
  has_privilege: boolean
  /** Whether the module contains data. */
  has_data: boolean
}

/**
 * Combined onboarding state for all modules.
 */
export interface OnboardingOverviewResponse {
  llm_provider: OnboardingStatusResponse
  tools: OnboardingStatusResponse
  /** Active connection owned by an enabled messaging bridge. */
  connections: OnboardingStatusResponse
  agents: OnboardingStatusResponse
  skills: OnboardingStatusResponse
  processes: OnboardingStatusResponse
  /** @deprecated Use skills.has_privilege. */
  skills_access: boolean
  /** @deprecated Use processes.has_privilege. */
  processes_access: boolean
}

/**
 * Fetch onboarding state for all modules.
 * @returns A promise containing the state of every module.
 */
async function getOverview(): Promise<OnboardingOverviewResponse> {
  const response = await api.get<OnboardingOverviewResponse>('/onboarding/overview')
  return response.data
}

const onboardingService = {
  getOverview,
}

export default onboardingService
