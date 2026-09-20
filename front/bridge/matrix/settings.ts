import type { BridgeSettingsContribution } from '@/core/params/settingsTypes'

export default {
    area: 'messaging',
    kind: 'matrix',
    label: 'Matrix',
    icon: 'grid_view',
    guideKey: 'messagingProviders.matrix.guide',
    stepsKey: 'messagingProviders.matrix.steps',
    docsUrl: 'https://spec.matrix.org/latest/client-server-api/',
    fields: [
        {
            name: 'MESSENGER_MATRIX_HOMESERVER',
            labelKey: 'messagingProviders.matrix.fields.homeserver',
            descriptionKey: 'messagingProviders.matrix.fields.homeserverHint',
        },
        {
            name: 'MESSENGER_MATRIX_SYNC_TIMEOUT_MS',
            labelKey: 'messagingProviders.matrix.fields.syncTimeout',
            input: 'integer',
            min: 0,
            advanced: true,
        },
    ],
} satisfies BridgeSettingsContribution
