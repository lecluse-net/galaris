import type { BridgeSettingsContribution } from '@/core/params/settingsTypes'

export default {
    area: 'messaging',
    kind: 'one_bot',
    label: 'OneBot 11',
    icon: 'smart_toy',
    guideKey: 'messagingProviders.oneBot.guide',
    stepsKey: 'messagingProviders.oneBot.steps',
    docsUrl: 'https://github.com/botuniverse/onebot-11',
    fields: [
        {
            name: 'MESSENGER_ONE_BOT_PLATFORM',
            labelKey: 'messagingProviders.oneBot.fields.platform',
            descriptionKey: 'messagingProviders.oneBot.fields.platformHint',
        },
        {
            name: 'MESSENGER_ONE_BOT_SECRET_KEY',
            labelKey: 'messagingProviders.oneBot.fields.secret',
            input: 'secret',
        },
    ],
} satisfies BridgeSettingsContribution
