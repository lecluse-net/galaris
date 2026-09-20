import type { Component } from 'vue'
import type { FileSizeUnit } from '@/core/util'

export type SettingsArea = 'messaging' | 'process' | 'harness'
export type SettingInput = 'text' | 'secret' | 'boolean' | 'checkbox' | 'integer' | 'number' | 'percentage-slider' | 'select' | 'textarea' | 'code' | 'prompt'
export type SettingCodeLanguage = 'json' | 'yaml' | 'markdown' | 'text'

export interface SettingOption {
    value: string
    labelKey: string
}

export interface SettingField {
    name: string
    labelKey: string
    descriptionKey?: string
    input?: SettingInput
    advanced?: boolean
    min?: number
    max?: number
    step?: number
    /** File sizes are entered in MB; bounds and API values use this storage unit. */
    sizeUnit?: FileSizeUnit
    options?: SettingOption[]
    codeLanguage?: SettingCodeLanguage
    visibleLines?: number
}

export interface SettingGroup {
    titleKey: string
    descriptionKey?: string
    fields: SettingField[]
}

export interface BridgeSettingsTestResult {
    ok: boolean
    message?: string
}

/** Settings contribution owned by one application module or external bridge. */
export interface BridgeSettingsContribution {
    area: SettingsArea
    placement?: 'provider' | 'overview'
    kind: string
    label: string
    icon: string
    guideKey: string
    stepsKey: string
    docsUrl: string
    fields: SettingField[]
    groups?: SettingGroup[]
    test?: () => Promise<BridgeSettingsTestResult>
    isAvailable?: () => boolean
    refreshAvailability?: () => Promise<void>
    component?: Component
    headerComponent?: Component
    taskExecutionComponent?: Component
}
