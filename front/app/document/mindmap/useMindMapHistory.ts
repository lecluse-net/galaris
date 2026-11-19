import { shallowRef, watch, type Ref } from 'vue'
import type { MindMap } from './model'

const historyLimit = 80
const historyBytes = 8_000_000

export function useMindMapHistory(source: Ref<string>) {
  const undo = shallowRef<string[]>([])
  const redo = shallowRef<string[]>([])
  let latest = source.value
  let group: string | undefined

  function push(stack: Ref<string[]>, value: string): void {
    const next = [...stack.value, value]
    let size = 0, start = next.length
    while (start > 0 && next.length - start < historyLimit) {
      // Keep the immediate previous version available even for a large map.
      size += next[start - 1]!.length * 2
      if (size > historyBytes && start < next.length) break
      start--
    }
    stack.value = next.slice(start)
  }

  function publish(value: string): void { latest = value; source.value = value }
  function clear(): void { undo.value = []; redo.value = []; group = undefined }
  watch(source, value => {
    if (value === latest) return
    latest = value
    clear()
  })

  function record(map: MindMap, editGroup?: string): void {
    const value = JSON.stringify(map)
    if (value === latest) return
    if (!editGroup || editGroup !== group) push(undo, latest)
    else if (undo.value.at(-1) === value) {
      undo.value = undo.value.slice(0, -1)
      editGroup = undefined
    }
    group = editGroup
    redo.value = []
    publish(value)
  }

  function restore(direction: 'undo' | 'redo'): boolean {
    const [from, to] = direction === 'undo' ? [undo, redo] : [redo, undo]
    const previous = from.value.at(-1)
    if (previous === undefined) return false
    push(to, latest)
    from.value = from.value.slice(0, -1)
    group = undefined
    publish(previous)
    return true
  }

  return { undo, redo, record, restore, clear, endGroup: () => { group = undefined } }
}
