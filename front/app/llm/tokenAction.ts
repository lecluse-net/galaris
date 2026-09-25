import { defineAsyncComponent } from 'vue'
import type { TokenActionContribution } from '@/core/user'

export default {
  name: 'llm-client-config',
  component: defineAsyncComponent(() => import('./components/ExternalClientConfigButton.vue')),
} satisfies TokenActionContribution
