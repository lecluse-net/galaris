import type { Component } from 'vue'

export interface TaskDiagnosticsContribution {
  component: Component
  canUse(hasPrivilege: (privilege: string) => boolean): boolean
}

const providers = import.meta.glob<{ default: TaskDiagnosticsContribution }>('../../../taskDiagnostics.ts', { eager: true })
export const taskDiagnostics = Object.values(providers)[0]?.default
