import type { Component } from 'vue'

// Profile extensions are composed by the authorize-owned profile page.

export interface ProfileContribution {
  component: Component
  identityComponent?: Component
  order?: number
  privilege?: string
}

interface ProfileModule { default: ProfileContribution }

const modules = import.meta.glob<ProfileModule>('../../app/*/profile.ts', { eager: true })

export const profileContributions = Object.values(modules)
  .map(module => module.default)
  .filter((item): item is ProfileContribution => Boolean(item?.component))
  .sort((left, right) => (left.order ?? 100) - (right.order ?? 100))
