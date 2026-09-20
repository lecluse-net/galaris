import { defineAsyncComponent } from 'vue'
import type { BridgeSettingsContribution } from '@/core/params'

export default {
    area: 'process',
    kind: 'n8n',
    label: 'n8n',
    icon: 'account_tree',
    guideKey: 'processSettings.n8n.guide',
    stepsKey: 'processSettings.n8n.steps',
    docsUrl: 'https://docs.n8n.io/connect/n8n-api/authentication',
    fields: [],
    component: defineAsyncComponent(() => import('./components/N8nSettingsPanel.vue')),
} satisfies BridgeSettingsContribution
