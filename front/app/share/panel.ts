import { defineAsyncView } from '@/core/util'

export const SharingPanel = defineAsyncView(() => import('./components/SharingPanel.vue'))
