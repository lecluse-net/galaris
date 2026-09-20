import { defineAsyncComponent } from 'vue'
import type { UserTabContribution } from '@/core/user'

export default {
  name: 'models',
  labelKey: 'personalVoice.models',
  icon: 'model_training',
  privilege: 'UPDATE_USER',
  formOnly: true,
  component: defineAsyncComponent(() => import('./components/PersonalLlmSettings.vue')),
} satisfies UserTabContribution
