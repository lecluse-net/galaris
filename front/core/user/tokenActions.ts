import type { Component } from 'vue'
import { modules as activeModules } from '@/modules'

export interface TokenActionContribution {
  name: string
  component: Component
}

const sources = import.meta.glob<{ default: TokenActionContribution }>(
  '../../app/*/tokenAction.ts', { eager: true },
)

export const tokenActions = Object.entries(sources)
  .filter(([path]) => activeModules.includes(`app/${path.split('/')[3]}`))
  .map(([, module]) => module.default)
