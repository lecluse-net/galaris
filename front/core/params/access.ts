import { parameterAccess } from './generatedAccess'

export function parameterReadPrivileges(name: string): readonly string[] {
  return parameterAccess[name] ?? []
}

export function parameterEditPrivilege(name: string): string {
  return parameterAccess[name]?.[1] ?? ''
}

const sections: Record<string, string> = {
  system: 'PARAMS', language: 'LANGUAGE_CONFIG', messaging: 'MESSAGING_CONFIG',
  memory: 'MEMORY_CONFIG', dream: 'DREAM_CONFIG', voice: 'VOICE_CONFIG', audio: 'AUDIO_CONFIG',
  process: 'PROCESS_CONFIG', tasks: 'TASK_CONFIG', harnesses: 'HARNESS_CONFIG', search: 'SEARCH_CONFIG',
  janus: 'JANUS_CONFIG', instructions: 'INSTRUCTION_CONFIG', logs: 'LOG_CONFIG',
}

export function sectionPrivileges(section: string): string[] {
  const prefix = sections[section]
  if (!prefix) return []
  if (section === 'instructions') return ['INSTRUCTION_CONFIG_ACCESS', 'INSTRUCTION_CONFIG_EDIT', 'GOAL_CONFIG_ACCESS', 'GOAL_CONFIG_EDIT']
  if (section === 'logs') return ['LOG_CONFIG_ACCESS', 'LOG_CONFIG_EDIT', 'TASK_PURGE', 'LLM_CALL_PURGE', 'INCIDENT_PURGE']
  return prefix === 'DREAM_CONFIG' ? ['DREAM_CONFIG_ACCESS', 'DREAM_EDIT'] : [`${prefix}_ACCESS`, `${prefix}_EDIT`]
}

export const preferencePrivileges = [...new Set(Object.keys(sections).flatMap(sectionPrivileges))]
