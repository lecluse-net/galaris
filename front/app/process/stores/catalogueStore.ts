import { defineStore } from 'pinia'
import { onScopeDispose, ref } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import type { CatalogueArchive, CatalogueKind } from '../services/catalogueService'

interface Pagination {
  page: number
  rowsPerPage: number
  sortBy?: string | null
  descending?: boolean
  rowsNumber?: number
}

/** Navigation preferences only: resource data is always reloaded under current ACLs. */
export const useProcessCatalogueStore = defineStore('processCatalogue', () => {
  let session = sessionGeneration()
  const filter = ref<string | null>('')
  const agentFilter = ref<number | null>(null)
  const kind = ref<CatalogueKind>('all')
  const archive = ref<CatalogueArchive>('active')
  const pagination = ref<Pagination>({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
  const expanded = ref<string[]>([])
  const runPages = ref<Partial<Record<string, Pagination>>>({})
  const sessionRevision = ref(0)

  function reset(): void {
    sessionRevision.value++
    filter.value = ''
    agentFilter.value = null
    kind.value = 'all'
    archive.value = 'active'
    pagination.value = { page: 1, rowsPerPage: 50, rowsNumber: 0 }
    expanded.value = []
    runPages.value = {}
  }
  function sessionChanged(event: Event): void {
    const current = sessionGeneration()
    if (current !== session || (event instanceof CustomEvent && event.detail === null)) reset()
    session = current
  }
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged)
  window.addEventListener('storage', sessionChanged)
  onScopeDispose(() => {
    window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged)
    window.removeEventListener('storage', sessionChanged)
  })

  return { filter, agentFilter, kind, archive, pagination, expanded, runPages, sessionRevision }
})
