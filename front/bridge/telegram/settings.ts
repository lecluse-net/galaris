import type { BridgeSettingsContribution } from '@/core/params/settingsTypes'

export default {
    area: 'messaging',
    kind: 'telegram',
    label: 'Telegram',
    icon: 'send',
    guideKey: 'messagingProviders.telegram.guide',
    stepsKey: 'messagingProviders.telegram.steps',
    docsUrl: 'https://core.telegram.org/bots/tutorial',
    fields: [
        {
            name: 'MESSENGER_TELEGRAM_POLL_TIMEOUT_S',
            labelKey: 'messagingProviders.telegram.fields.pollTimeout',
            input: 'integer',
            min: 1,
            max: 50,
            advanced: true,
        },
        {
            name: 'MESSENGER_TELEGRAM_UPDATE_MAX_AGE_SECONDS',
            labelKey: 'messagingProviders.telegram.fields.maxAge',
            input: 'integer',
            min: 0,
            advanced: true,
        },
    ],
} satisfies BridgeSettingsContribution
