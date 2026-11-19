import { ref, watch } from 'vue'
import { usePaginatedQuery, type QueryPagination } from '@/core/util'
import { useProcessCatalogueStore } from '../stores/catalogueStore'
import { useProcessRunRefresh } from './useProcessRunRefresh'

interface RunHistoryOptions {
  context: () => string | number | undefined
  navigationKey: () => string | undefined
  revision: () => number | undefined
  defaultSort?: string
  onContextReset?: () => void
}

export function useProcessRunHistory<Result extends { total: number }>(
  { context, navigationKey, revision, defaultSort, onContextReset }: RunHistoryOptions,
  fetchPage: (page: Readonly<QueryPagination>) => Promise<Result>,
) {
  const navigation = useProcessCatalogueStore()
  const pagination = ref<QueryPagination>({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
  const { result, loading, error, load, reset } = usePaginatedQuery(pagination, fetchPage)

  function sort({ sortBy, descending }: Partial<QueryPagination>) {
    return defaultSort === undefined ? {} : { sortBy: sortBy || defaultSort, descending: descending ?? true }
  }

  function setPagination(value: QueryPagination): void {
    pagination.value = { ...value, ...sort(value) }
  }

  function request({ pagination: requested }: { pagination: Omit<QueryPagination, 'rowsNumber'> }): void {
    setPagination({ ...pagination.value, ...requested })
    void load()
  }

  watch([context, navigationKey, () => navigation.sessionRevision, revision], ([current, key, session], previous) => {
    if (!previous.length || current !== previous[0] || key !== previous[1] || session !== previous[2]) {
      const saved = key === undefined ? undefined : navigation.runPages[key]
      onContextReset?.()
      reset()
      pagination.value = {
        page: saved?.page ?? 1,
        rowsPerPage: saved?.rowsPerPage ?? 50,
        rowsNumber: 0,
        ...sort(saved ?? {}),
      }
    }
    void load()
  }, { immediate: true })

  watch(pagination, value => {
    const key = navigationKey()
    if (key === undefined) return
    navigation.runPages[key] = { page: value.page, rowsPerPage: value.rowsPerPage, ...sort(value) }
  }, { deep: true })
  useProcessRunRefresh(load, loading)

  return { pagination, result, loading, error, load, request, setPagination }
}
