import type { BridgeSettingsContribution } from '@/core/params/settingsTypes'

export default {
    area: 'messaging',
    kind: 'whatsapp',
    label: 'WhatsApp',
    icon: 'chat',
    guideKey: 'messagingProviders.whatsapp.guide',
    stepsKey: 'messagingProviders.whatsapp.steps',
    docsUrl: 'https://developers.facebook.com/docs/whatsapp/cloud-api/get-started',
    fields: [
        {
            name: 'MESSENGER_WHATSAPP_GRAPH_VERSION',
            labelKey: 'messagingProviders.whatsapp.fields.graphVersion',
        },
        {
            name: 'MESSENGER_WHATSAPP_APP_SECRET',
            labelKey: 'messagingProviders.whatsapp.fields.appSecret',
            input: 'secret',
        },
        {
            name: 'MESSENGER_WHATSAPP_VERIFY_TOKEN',
            labelKey: 'messagingProviders.whatsapp.fields.verifyToken',
            input: 'secret',
        },
        {
            name: 'MESSENGER_WHATSAPP_GRAPH_URL',
            labelKey: 'messagingProviders.whatsapp.fields.graphUrl',
            advanced: true,
        },
        {
            name: 'MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES',
            sizeUnit: 'bytes',
            labelKey: 'messagingProviders.whatsapp.fields.webhookMaxBytes',
            input: 'integer',
            min: 1024,
            advanced: true,
        },
        {
            name: 'MESSENGER_WHATSAPP_HTTP_TIMEOUT_S',
            labelKey: 'messagingProviders.whatsapp.fields.httpTimeout',
            input: 'number',
            min: 1,
            max: 120,
            advanced: true,
        },
    ],
} satisfies BridgeSettingsContribution
