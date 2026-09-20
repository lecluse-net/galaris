import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref, watch } from 'vue'
import { websocket } from '@/core/websocket'
import { memoryService } from '../services/memoryService'
import type {
  MemoryItem,
  MemoryItemCreate,
  MemoryItemDetail,
  MemoryItemUpdate,
  MemoryFinding,
  MemoryLink,
  MemoryRevision,
  MemoryRelationType,
  MemorySearchHit,
  MemorySortField,
  MemoryType,
} from '../types'

const MEMORY_PAGE_SIZE_OPTIONS = [10, 20, 50, 100, 500]
const DEFAULT_MEMORY_PAGE_SIZE = 50
const MAX_MEMORY_PAGE_SIZE = 500

export const useMemoryStore = defineStore('memory', () => {
  const hits = ref<MemorySearchHit[]>([])
  const currentItem = ref<MemoryItemDetail | null>(null)
  const revisions = ref<MemoryRevision[]>([])
  const revisionPageSize = ref(50)
  const revisionsHaveMore = ref(false)
  const revisionsLoading = ref(false)
  let detailRequest = 0
  let searchRequest = 0
  const links = ref<MemoryLink[]>([])
  const findings = ref<MemoryFinding[]>([])
  const selectedAgentId = ref<number | null>(null)
  const selectedTypes = ref<MemoryType[]>([])
  const selectedTopicItemId = ref<string | null>(null)
  const selectedContactItemId = ref<string | null>(null)
  const query = ref('')
  const loading = ref(false)
  const detailLoading = ref(false)
  const saving = ref(false)
  const error = ref<unknown>(null)
  const hasMore = ref(false)
  const page = ref(1)
  const rowsPerPage = ref(DEFAULT_MEMORY_PAGE_SIZE)
  const total = ref(0)
  const sortBy = ref<MemorySortField | null>(null)
  const sortDescending = ref(true)

  const items = computed(() => hits.value.map(hit => hit.item))

  async function search(options: {
    page?: number
    rowsPerPage?: number
    resetPage?: boolean
    sortBy?: MemorySortField | null
    sortDescending?: boolean
  } = {}): Promise<void> {
    const request = ++searchRequest
    const agentId = selectedAgentId.value
    const previousPage = page.value
    const previousRowsPerPage = rowsPerPage.value
    const previousSortBy = sortBy.value
    const previousSortDescending = sortDescending.value
    if (options.rowsPerPage !== undefined) {
      rowsPerPage.value = Math.max(1, Math.min(MAX_MEMORY_PAGE_SIZE, options.rowsPerPage))
    }
    if (options.sortBy !== undefined) sortBy.value = options.sortBy
    if (options.sortDescending !== undefined) sortDescending.value = options.sortDescending
    page.value = options.resetPage
      ? 1
      : Math.max(1, options.page ?? page.value)
    if (selectedAgentId.value === null) {
      hits.value = []
      hasMore.value = false
      total.value = 0
      page.value = 1
      return
    }
    loading.value = true
    error.value = null
    try {
      let result = await memoryService.browse({
        agentId: selectedAgentId.value,
        query: query.value,
        memoryTypes: selectedTypes.value,
        topicItemId: selectedTopicItemId.value,
        contactItemId: selectedContactItemId.value,
        sortBy: sortBy.value,
        sortDescending: sortDescending.value,
        limit: rowsPerPage.value,
        offset: (page.value - 1) * rowsPerPage.value,
      })
      if (request !== searchRequest || agentId !== selectedAgentId.value) return
      const lastPage = Math.max(1, Math.ceil(result.total / rowsPerPage.value))
      if (page.value > lastPage) {
        page.value = lastPage
        result = await memoryService.browse({
          agentId: selectedAgentId.value,
          query: query.value,
          memoryTypes: selectedTypes.value,
          topicItemId: selectedTopicItemId.value,
          contactItemId: selectedContactItemId.value,
          sortBy: sortBy.value,
          sortDescending: sortDescending.value,
          limit: rowsPerPage.value,
          offset: (page.value - 1) * rowsPerPage.value,
        })
      }
      const newFindings = await memoryService.listFindings(selectedAgentId.value)
      if (request !== searchRequest || agentId !== selectedAgentId.value) return
      hits.value = result.hits
      findings.value = newFindings
      total.value = result.total
      hasMore.value = result.has_more
    } catch (caught) {
      if (request !== searchRequest || agentId !== selectedAgentId.value) return
      page.value = previousPage
      rowsPerPage.value = previousRowsPerPage
      sortBy.value = previousSortBy
      sortDescending.value = previousSortDescending
      error.value = caught
      throw caught
    } finally {
      if (request === searchRequest) loading.value = false
    }
  }

  function invalidateAccess(): void {
    searchRequest++
    detailRequest++
    hits.value = []
    findings.value = []
    currentItem.value = null
    revisions.value = []
    links.value = []
    total.value = 0
    hasMore.value = false
    loading.value = false
    detailLoading.value = false
    revisionsLoading.value = false
    revisionsHaveMore.value = false
  }

  function refreshAccess(): void {
    invalidateAccess()
    void search().catch(() => { /* The store exposes the refresh error. */ })
  }
  watch(selectedAgentId, invalidateAccess, { flush: 'sync' })
  websocket.createWebsocket()
  websocket.onEvent('memory', 'invalidate', refreshAccess)
  websocket.onConnect(refreshAccess)
  onScopeDispose(() => {
    websocket.offEvent('memory', 'invalidate', refreshAccess)
    websocket.offConnect(refreshAccess)
  })

  async function openItem(id: string, revision?: number): Promise<MemoryItemDetail> {
    if (selectedAgentId.value === null) throw new Error('An agent is required')
    const request = ++detailRequest
    const reuseRevisions = revision !== undefined && currentItem.value?.id === id && revisions.value.length > 0
    detailLoading.value = true
    try {
      const [item, itemRevisions, itemLinks] = await Promise.all([
        memoryService.getItem(id, selectedAgentId.value, revision),
        reuseRevisions ? Promise.resolve(revisions.value) : memoryService.listRevisions(id, selectedAgentId.value, revisionPageSize.value),
        memoryService.listLinks(id, selectedAgentId.value),
      ])
      if (request === detailRequest) {
        currentItem.value = item
        revisions.value = itemRevisions
        if (!reuseRevisions) revisionsHaveMore.value = itemRevisions.length === revisionPageSize.value
        links.value = itemLinks
      }
      return item
    } finally {
      if (request === detailRequest) detailLoading.value = false
    }
  }

  async function loadMoreRevisions(reset = false): Promise<void> {
    if (selectedAgentId.value === null || !currentItem.value || revisionsLoading.value) return
    const request = detailRequest
    const id = currentItem.value.id
    revisionsLoading.value = true
    try {
      const page = await memoryService.listRevisions(id, selectedAgentId.value, revisionPageSize.value, reset ? 0 : revisions.value.length)
      if (request !== detailRequest || currentItem.value?.id !== id) return
      revisions.value = reset ? page : [...revisions.value, ...page]
      revisionsHaveMore.value = page.length === revisionPageSize.value
    } finally { revisionsLoading.value = false }
  }

  function findingsFor(itemId: string): MemoryFinding[] {
    return findings.value.filter(finding => (
      finding.primary_item_id === itemId || finding.related_item_id === itemId
    ))
  }

  async function resolveFinding(
    finding: MemoryFinding,
    action: 'apply' | 'dismiss',
    canonicalItemId?: string,
  ): Promise<void> {
    saving.value = true
    try {
      if (action === 'apply') await memoryService.applyFinding(finding.id, canonicalItemId)
      else await memoryService.dismissFinding(finding.id)
      findings.value = findings.value.filter(candidate => candidate.id !== finding.id)
    } finally {
      saving.value = false
    }
    void refreshAfterFindingResolution()
  }

  async function refreshAfterFindingResolution(): Promise<void> {
    try {
      await search()
      if (currentItem.value === null) return
      const currentId = currentItem.value.id
      const stillExists = hits.value.some(hit => hit.item.id === currentId)
      if (stillExists) await openItem(currentId)
      else currentItem.value = null
    } catch {
      // search() already exposes the refresh error through the store. The
      // confirmed finding action must not keep its dialog open indefinitely.
    }
  }

  async function createItem(data: MemoryItemCreate): Promise<MemoryItem> {
    saving.value = true
    try {
      const item = await memoryService.createItem(data)
      await search()
      return item
    } finally {
      saving.value = false
    }
  }

  async function updateItem(id: string, data: MemoryItemUpdate): Promise<MemoryItem> {
    if (selectedAgentId.value === null) throw new Error('An agent is required')
    saving.value = true
    try {
      const item = await memoryService.updateItem(id, selectedAgentId.value, data)
      await search()
      await openItem(id)
      return item
    } finally {
      saving.value = false
    }
  }

  async function forgetItem(id: string): Promise<void> {
    if (selectedAgentId.value === null) throw new Error('An agent is required')
    saving.value = true
    try {
      await memoryService.forgetItem(id, selectedAgentId.value)
      currentItem.value = null
      revisions.value = []
      links.value = []
      await search()
    } finally {
      saving.value = false
    }
  }

  async function setItemGrant(agentId: number, canWrite: boolean): Promise<void> {
    if (currentItem.value === null || selectedAgentId.value === null) return
    saving.value = true
    try {
      await memoryService.setItemGrant(currentItem.value.id, agentId, canWrite)
      await openItem(currentItem.value.id)
      await search()
    } finally {
      saving.value = false
    }
  }

  async function removeItemGrant(agentId: number): Promise<void> {
    if (currentItem.value === null || selectedAgentId.value === null) return
    saving.value = true
    try {
      await memoryService.removeItemGrant(currentItem.value.id, agentId)
      await openItem(currentItem.value.id)
      await search()
    } finally {
      saving.value = false
    }
  }

  async function createLink(targetItemId: string, relationType: MemoryRelationType): Promise<void> {
    if (selectedAgentId.value === null || currentItem.value === null) return
    saving.value = true
    try {
      await memoryService.createLink({
        source_item_id: currentItem.value.id,
        target_item_id: targetItemId,
        relation_type: relationType,
      }, selectedAgentId.value)
      links.value = await memoryService.listLinks(currentItem.value.id, selectedAgentId.value)
    } finally {
      saving.value = false
    }
  }

  return {
    hits,
    items,
    currentItem,
    revisions,
    revisionPageSize,
    revisionsHaveMore,
    revisionsLoading,
    loadMoreRevisions,
    links,
    findings,
    selectedAgentId,
    selectedTypes,
    selectedTopicItemId,
    selectedContactItemId,
    query,
    loading,
    detailLoading,
    saving,
    error,
    hasMore,
    page,
    rowsPerPage,
    rowsPerPageOptions: MEMORY_PAGE_SIZE_OPTIONS,
    total,
    sortBy,
    sortDescending,
    search,
    openItem,
    findingsFor,
    resolveFinding,
    createItem,
    updateItem,
    forgetItem,
    setItemGrant,
    removeItemGrant,
    createLink,
  }
})
