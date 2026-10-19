import { computed, ref } from 'vue'

export function useDocumentHistory() {
  const visits = ref<(string | null)[]>([])
  const position = ref(-1)
  function target(direction: -1 | 1): { id: string; position: number } | null {
    for (let index = position.value + direction; index >= 0 && index < visits.value.length; index += direction) {
      const id = visits.value[index]
      if (id) return { id, position: index }
    }
    return null
  }
  function record(id: string, index?: number): void {
    if (index !== undefined) position.value = index
    else if (visits.value[position.value] !== id) {
      visits.value = [...visits.value.slice(0, position.value + 1), id]
      position.value = visits.value.length - 1
    }
  }
  function forget(id: string): void { visits.value = visits.value.map(value => value === id ? null : value) }
  function reset(): void { visits.value = []; position.value = -1 }
  return { target, record, forget, reset, canGoBack: computed(() => target(-1) !== null), canGoForward: computed(() => target(1) !== null) }
}
