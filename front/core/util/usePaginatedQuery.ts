import { onScopeDispose, ref, shallowRef, type Ref } from 'vue'

export interface QueryPagination {
  page: number
  rowsPerPage: number
  rowsNumber: number
  sortBy?: string | null
  descending?: boolean
}

/** Local query state. Consumers own the context, pagination persistence and API contract. */
export function usePaginatedQuery<Result extends { total: number }>(
  pagination: Ref<QueryPagination>,
  fetchPage: (page: Readonly<QueryPagination>) => Promise<Result>,
) {
  const result = shallowRef<Result | null>(null)
  const loading = ref(false)
  const error = ref(false)
  let generation = 0
  let disposed = false

  function reset(): void {
    generation++
    result.value = null
    error.value = false
    loading.value = false
  }

  async function load(): Promise<void> {
    if (disposed) return
    const token = ++generation
    loading.value = true
    error.value = false
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
        const page = { ...pagination.value }
        const next = await fetchPage(page)
        if (token !== generation) return
        const lastPage = Math.max(1, Math.ceil(next.total / page.rowsPerPage))
        if (page.page > lastPage) {
          pagination.value.page = lastPage
          // A constantly shrinking result must not cause an unbounded request loop.
          if (attempt === 1) throw new Error('Pagination changed during page recovery')
          continue
        }
        result.value = next
        pagination.value.rowsNumber = next.total
        return
      }
    } catch {
      if (token === generation) error.value = true
    } finally {
      if (token === generation) loading.value = false
    }
  }

  onScopeDispose(() => { disposed = true; reset() })
  return { result, loading, error, load, reset }
}
