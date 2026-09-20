import type { BridgeSettingsContribution } from '@/core/params/settingsTypes'
import HermesConfigurationHint from './components/HermesConfigurationHint.vue'

export default {
    area: 'harness',
    kind: 'hermes',
    label: 'Hermès',
    icon: 'smart_toy',
    guideKey: 'harnessSettings.hermes.guide',
    stepsKey: 'harnessSettings.hermes.steps',
    docsUrl: 'https://github.com/NousResearch/hermes-agent',
    fields: [],
    headerComponent: HermesConfigurationHint,
    groups: [
        {
            titleKey: 'harnessSettings.hermes.defaults.title',
            descriptionKey: 'harnessSettings.hermes.defaults.description',
            fields: [
                {
                    name: 'hermes.default.config',
                    labelKey: 'harnessSettings.hermes.fields.defaultConfig',
                    descriptionKey: 'harnessSettings.hermes.fields.defaultConfigHint',
                    input: 'code',
                    codeLanguage: 'yaml',
                    visibleLines: 12,
                },
                {
                    name: 'hermes.default.data-env',
                    labelKey: 'harnessSettings.hermes.fields.defaultDataEnv',
                    descriptionKey: 'harnessSettings.hermes.fields.defaultDataEnvHint',
                    input: 'textarea',
                    advanced: true,
                },
            ],
        },
    ],
} satisfies BridgeSettingsContribution
