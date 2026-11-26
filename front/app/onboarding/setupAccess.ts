import { computed } from 'vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useOnboardingStore } from './stores/onboardingStore'

export function useSetupAccess() {
  const access = usePrivilegeStore()
  const onboarding = useOnboardingStore()
  const canView = computed(() => ({
    language: access.hasAnyPrivilege([privileges.LANGUAGE_CONFIG_ACCESS, privileges.LANGUAGE_CONFIG_EDIT]),
    llm: access.hasAnyPrivilege([privileges.LLM_PROVIDER_ACCESS, privileges.LLM_PROVIDER_EDIT]),
    agent: access.hasAnyPrivilege([privileges.AGENT_ACCESS, privileges.AGENT_EDIT]),
    connections: access.hasAnyPrivilege([privileges.CONNECTION_ACCESS, privileges.CONNECTION_EDIT]),
    tools: access.hasAnyPrivilege([privileges.SERVICE_ACCESS, privileges.SERVICE_EDIT]),
    skills: access.hasAnyPrivilege([privileges.SKILL_ACCESS, privileges.SKILL_EDIT, privileges.SKILL_ASSIGN]),
    processes: access.hasAnyPrivilege([privileges.PROCESS_READ, privileges.PROCESS_EDIT, privileges.PROCESS_ADMIN]),
  }))
  const canEdit = computed(() => ({
    language: access.hasPrivilege(privileges.LANGUAGE_CONFIG_EDIT),
    llm: access.hasPrivilege(privileges.LLM_PROVIDER_EDIT),
    agent: access.hasPrivilege(privileges.AGENT_EDIT),
    connections: access.hasPrivilege(privileges.CONNECTION_EDIT),
    tools: access.hasPrivilege(privileges.SERVICE_EDIT),
    skills: access.hasPrivilege(privileges.SKILL_ASSIGN)
      || (access.hasPrivilege(privileges.SKILL_EDIT) && access.hasPrivilege(privileges.AGENT_MANAGE_ALL)),
    processes: access.hasAnyPrivilege([privileges.PROCESS_EDIT, privileges.PROCESS_ADMIN]),
  }))
  const canViewSetup = computed(() => Object.values(canView.value).some(Boolean))
  const canConfigureSetup = computed(() => canEdit.value.language || canEdit.value.llm || canEdit.value.agent)
  const hasMissingSetup = computed(() => onboarding.isLoaded && (
    (canEdit.value.language && onboarding.languageConfigured === false)
    || (canEdit.value.llm && onboarding.llmProvider?.has_data === false)
    || (canEdit.value.agent && onboarding.agents?.has_data === false)
  ))

  return { canView, canEdit, canViewSetup, canConfigureSetup, hasMissingSetup }
}
