import type { BridgeSettingsContribution } from '@/core/params/settingsTypes'

export default {
    area: 'messaging',
    kind: 'nextcloud_talk',
    label: 'Nextcloud Talk',
    icon: 'forum',
    guideKey: 'messagingProviders.nextcloudTalk.guide',
    stepsKey: 'messagingProviders.nextcloudTalk.steps',
    docsUrl: 'https://nextcloud-talk.readthedocs.io/en/stable/chat/',
    fields: [
        {
            name: 'MESSENGER_NEXTCLOUD_TALK_INBOUND',
            labelKey: 'messagingProviders.nextcloudTalk.fields.inbound',
            input: 'select',
            options: [
                { value: 'polling', labelKey: 'messagingProviders.nextcloudTalk.options.polling' },
                { value: 'signaling', labelKey: 'messagingProviders.nextcloudTalk.options.signaling' },
            ],
        },
        {
            name: 'MESSENGER_NEXTCLOUD_TALK_HPB_URL',
            labelKey: 'messagingProviders.nextcloudTalk.fields.hpbUrl',
            advanced: true,
        },
        {
            name: 'MESSENGER_NEXTCLOUD_TALK_ROOM_DISCOVERY_INTERVAL',
            labelKey: 'messagingProviders.nextcloudTalk.fields.discoveryInterval',
            input: 'number',
            min: 1,
            step: 1,
            advanced: true,
        },
        {
            name: 'MESSENGER_NEXTCLOUD_TALK_LONGPOLL_TIMEOUT',
            labelKey: 'messagingProviders.nextcloudTalk.fields.longpollTimeout',
            input: 'integer',
            min: 1,
            advanced: true,
        },
    ],
} satisfies BridgeSettingsContribution
