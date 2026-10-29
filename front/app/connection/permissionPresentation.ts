import { solaireCss, type SolaireColor } from '@/core/util'
import type { PermissionState } from './services/permissionDashboard'

interface PermissionAppearance { icon: string; color: SolaireColor }

export const permissionStates: Record<Exclude<PermissionState, 'all'>, PermissionAppearance> = {
  allowed: { icon: 'check', color: 'green' },
  denied: { icon: 'close', color: 'red' },
  ask: { icon: 'help_outline', color: 'orange' },
  pending: { icon: 'pending_actions', color: 'orange' },
}

const inherited: PermissionAppearance = { icon: 'call_merge', color: 'gray' }
const choices: Record<string, PermissionAppearance> = {
  enabled: permissionStates.allowed, allow: permissionStates.allowed,
  disabled: permissionStates.denied, deny: permissionStates.denied,
  ask: permissionStates.ask, pending: permissionStates.pending,
  default: inherited, inherit: inherited,
  allow_always: { icon: 'done_all', color: 'green' },
  deny_always: { icon: 'block', color: 'red' },
  expired: { icon: 'event_busy', color: 'gray' },
  invalidated: { icon: 'event_busy', color: 'gray' },
  failed: { icon: 'warning', color: 'red' },
  outcome_unknown: { icon: 'warning', color: 'red' },
}
const scopes: Record<string, PermissionAppearance> = {
  default: inherited,
  none: { icon: 'block', color: 'red' },
  usage: { icon: 'visibility', color: 'cyan' },
  personal: { icon: 'person', color: 'blue' },
  team: { icon: 'groups', color: 'iris' },
  all: { icon: 'public', color: 'violet' },
}

export function permissionChoiceAppearance(control: string, value: string): PermissionAppearance {
  return (control === 'scope' ? scopes[value] : choices[value]) ?? { icon: 'tune', color: 'gray' }
}

export function permissionColorStyle(color: SolaireColor) {
  return {
    '--permission-accent': solaireCss[color].accent,
    '--permission-light': solaireCss[color].light,
    '--permission-dark': solaireCss[color].dark,
    '--permission-on-accent': ['orange', 'cyan', 'yellow', 'salmon'].includes(color) ? '#292C30' : '#FFFFFF',
  }
}
