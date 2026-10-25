import type { BridgeSettingsContribution } from './settingsTypes'
import type { Component } from 'vue'

interface SettingsModule {
    default?: BridgeSettingsContribution
    messagingSetupComponents?: Record<string, Component>
}

const modules = import.meta.glob<SettingsModule>(
    ['../../app/*/settings.ts', '../../bridge/*/settings.ts'],
    { eager: true },
)

const contributions = Object.values(modules)
    .map(module => module.default)
    .filter((item): item is BridgeSettingsContribution => Boolean(item?.kind))

export const messagingSetupComponents = Object.fromEntries(
    Object.values(modules).flatMap(module => Object.entries(module.messagingSetupComponents ?? {})),
)

export const messagingBridgeSettings = contributions
    .filter(item => item.area === 'messaging')
    .sort((left, right) => left.label.localeCompare(right.label))

export const processBridgeSettings = contributions
    .filter(item => item.area === 'process')

export const harnessBridgeSettings = contributions
    .filter(item => item.area === 'harness' && item.placement !== 'overview')
    .sort((left, right) => left.label.localeCompare(right.label))

export const harnessOverviewSettings = contributions
    .filter(item => item.area === 'harness' && item.placement === 'overview')

export const taskExecutionSettings = contributions
    .filter(item => item.taskExecutionComponent)
