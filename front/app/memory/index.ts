import { defineAsyncComponent } from 'vue'

export { memoryService } from './services/memoryService'
export const MemoryItemDialog = defineAsyncComponent(() => import('./components/MemoryItemDialog.vue'))
export type { MemoryAgendaOccurrence } from './services/memoryService'
export type { MemoryItem, MemoryItemDetail } from './types'
export { default as ContactResourceDialog } from './components/ContactResourceDialog.vue'
export { default as ContactResourceCard } from './components/ContactResourceCard.vue'
export { contactResourceId } from './contactResource'
export { default as ContactSelect } from './components/ContactSelect.vue'
