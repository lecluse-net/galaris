import { defineAsyncComponent } from 'vue'
export const CalendarWorkspace = defineAsyncComponent(() => import('./components/CalendarWorkspace.vue'))
export const CalendarResourceDialog = defineAsyncComponent(() => import('./components/CalendarResourceDialog.vue'))
export const CalendarSyncMonitor = defineAsyncComponent(() => import('./components/CalendarSyncMonitor.vue'))
export { calendarService } from './services/calendarService'
export type { CalendarFeed, CalendarConnectionStatus, CalendarReminder } from './services/calendarService'
