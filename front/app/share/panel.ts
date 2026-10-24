import { defineAsyncView } from '@/core/util/facade'

export const SharingPanel = defineAsyncView(() => import('./components/SharingPanel.vue'))
