import type { Component } from 'vue'
import { modules as activeModules } from '../../modules'

export interface ShellContribution {
  component: Component
  order?: number
}

interface ShellModule { default: ShellContribution }

const modules = import.meta.glob<ShellModule>('../*/shell.ts', { eager: true })

export const shellContributions = activeModules
  .map(modulePath => {
    const key = Object.keys(modules).find(candidate => candidate.endsWith(`${modulePath.replace('app/', '')}/shell.ts`))
    return key ? modules[key]?.default : undefined
  })
  .filter((item): item is ShellContribution => Boolean(item?.component))
  .sort((left, right) => (left.order ?? 100) - (right.order ?? 100))
